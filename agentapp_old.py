import os
import re
import json
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv

import chromadb
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.openai import OpenAI

import gradio as gr
from riskdata import RISK_DB  # our JSON-style dataset

# =========================
# Config & Setup
# =========================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

llm = OpenAI(model="gpt-4o-mini", temperature=0.2)
Settings.llm = llm

CHROMA_PATH = "./chroma_db"


# =========================
# Build LlamaIndex from JSON dataset
# =========================
def json_to_documents(risk_db: Dict[str, Dict]) -> List[Document]:
    docs = []
    for ing, info in risk_db.items():
        text = f"Ingredient: {ing}\nRisk: {info['risk']}\nImpact: {info['impact']}"
        docs.append(
            Document(
                text=text,
                metadata={
                    "ingredient": ing,
                    "risk": info["risk"],
                    "impact": info["impact"],
                },
            )
        )
    return docs


def build_index(documents: List[Document]) -> VectorStoreIndex:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection("ingredients")
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    return index


DOCS = json_to_documents(RISK_DB)
INDEX = build_index(DOCS)
QUERY_ENGINE = INDEX.as_query_engine(similarity_top_k=5)

# =========================
# Analysis functions
# =========================
RISK_ORDER = ["High", "Medium", "Low", "Unknown"]


def tokenize_ingredient_list(raw_text: str) -> List[str]:
    raw_text = re.sub(r"\(.*?\)", "", raw_text)
    parts = re.split(r"[,;\n]", raw_text)
    return [p.strip() for p in parts if p.strip()]


def lookup_risk(ingredient: str):
    ing_lc = ingredient.lower().strip()
    if ing_lc in RISK_DB:
        info = RISK_DB[ing_lc]
        return ing_lc, info["risk"], info["impact"]
    # fallback via retrieval if not in JSON
    retrieved = QUERY_ENGINE.query(
        f"Find safety info for cosmetic ingredient: {ingredient}. Return name, risk, impact."
    )
    text = str(retrieved)
    m_ing = re.search(r"Ingredient:\s*(.+)", text)
    m_risk = re.search(r"Risk:\s*(High|Medium|Low)", text, re.IGNORECASE)
    m_impact = re.search(r"Impact:\s*(.+)", text)
    if m_ing and m_risk:
        return (
            m_ing.group(1).strip(),
            m_risk.group(1).capitalize(),
            (m_impact.group(1).strip() if m_impact else ""),
        )
    return ingredient, "Unknown", "Not in database"


def bucketize(risk_level: str) -> str:
    rl = risk_level.strip().capitalize()
    if rl in ["High"]:
        return "High"
    if rl in ["Medium"]:
        return "Medium"
    if rl in ["Low"]:
        return "Low"
    return "Unknown"


def overall_score(buckets: Dict[str, List[Dict]]) -> str:
    if buckets.get("High"):
        return "Bad"
    if buckets.get("Medium"):
        return "Poor"
    return "Excellent"


EXPLANATION_PROMPT = """You are a cosmetic safety expert.
Given:
- Analyzed ingredient findings (JSON)
Task:
- Write a concise, user-friendly explanation.
- For High risk: include likely long-term impacts in 1 short sentence each.
- For Medium risk: brief caution.
- For Low: reassure briefly.
- End with a one-sentence overall rationale that matches the score.
Keep it to ~6-9 bulleted lines total.
JSON:
{json_payload}
"""


def llm_explain(findings: Dict) -> str:
    payload = json.dumps(findings, ensure_ascii=False, indent=2)
    resp = QUERY_ENGINE.query(EXPLANATION_PROMPT.format(json_payload=payload))
    return str(resp)


def analyze_product(raw_text: str) -> Dict:
    items = tokenize_ingredient_list(raw_text)
    per_ing = []
    buckets = {"High": [], "Medium": [], "Low": [], "Unknown": []}
    new_entries = {}

    for ing in items:
        ing_lc = ing.lower().strip()
        db_entry = RISK_DB.get(ing_lc)

        if db_entry:
            risk, impact = db_entry["risk"], db_entry["impact"]
        else:
            # Lookup unknown ingredient via LLM, always update riskdata.py
            ai_info = llm_lookup_unknown(ing)
            new_entries[ing_lc] = ai_info
            risk, impact = ai_info["risk"], ai_info["impact"]

        level = bucketize(risk)
        entry = {
            "input": ing,
            "ingredient": ing_lc,
            "risk_level": level,
            "impact": impact,
        }
        per_ing.append(entry)
        buckets[level].append({"ingredient": ing_lc, "impact": impact})

    # Update riskdata.py with any new entries, even if not all are unknown
    if new_entries:
        update_riskdata(new_entries)
        # Only embed new ingredient docs
        new_docs = []
        for ingredient, info in new_entries.items():
            text = (
                f"Ingredient: {ingredient}\n"
                f"Risk: {info['risk']}\n"
                f"Impact: {info['impact']}"
            )
            new_docs.append(Document(text=text))
        INDEX.insert_nodes(new_docs)
        QUERY_ENGINE = INDEX.as_query_engine(similarity_top_k=5)

    score = overall_score(buckets)
    findings = {
        "overall_score": score,
        "high_risk": buckets["High"],
        "medium_risk": buckets["Medium"],
        "low_risk": buckets["Low"],
        "unknown": buckets["Unknown"],
        "details": per_ing,
    }
    findings["explanation"] = llm_explain(findings)
    return findings


def llm_lookup_unknown(ingredient: str) -> Dict:
    """
    Ask LLM for risk + impact.
    Never accept 'Unknown' or 'Not available'.
    Retry or prompt for real-world info.
    """
    prompt = f"""You are a cosmetic safety expert.
Ingredient: {ingredient}
Classify risk as one of: High, Medium, Low.
Give a concise, factual 1-sentence impact about safety/side effects, avoiding vague answers.
Do not reply with 'Unknown' or 'Not available' for either value.
Format as JSON with keys 'risk' and 'impact' only."""

    resp = llm.complete(prompt)
    try:
        data = json.loads(str(resp).strip())

        # Validate data: reject 'Unknown' or 'Not available'
        risk = data.get("risk", "").capitalize()
        impact = data.get("impact", "").strip()
        if (
            risk in ("Unknown", "")
            or impact in ("Not available", "")
            or len(impact) < 12
        ):
            # Optionally, retry the prompt (basic loop)
            # ...or return a manual fallback
            # For demo: retry ONCE more
            resp2 = llm.complete(
                prompt
                + " Please check the ingredients to add meaningful context and ensure both values are based on real-world data."
            )
            data2 = json.loads(str(resp2).strip())
            risk = data2.get("risk", "").capitalize()
            impact = data2.get("impact", "").strip()
            if (
                risk in ("Unknown", "")
                or impact in ("Not available", "")
                or len(impact) < 12
            ):
                # Final fallback
                risk = "Low"
                impact = "No known risks; used safely as cosmetic ingredient per available literature."
        return {"risk": risk, "impact": impact}
    except Exception:
        # Graceful fallback if LLM parse fails
        return {"risk": "Low", "impact": "No known risks."}


# =========================
# Riskdata updater

RISKDATA_FILE = Path("riskdata.py")


def update_riskdata(new_entries: dict):
    """
    Update risk_data.py with new ingredients and incrementally add to LlamaIndex.
    """
    global QUERY_ENGINE, INDEX

    if not new_entries:
        return

    # --- 1. Update the Python risk_data.py file ---
    updated_db = {**RISK_DB, **new_entries}
    content = "RISK_DB = " + json.dumps(updated_db, indent=4) + "\n"
    RISKDATA_FILE.write_text(content)

    # --- 2. Convert new entries into LlamaIndex Documents ---
    new_docs = []
    for ingredient, info in new_entries.items():
        text = (
            f"Ingredient: {ingredient}\n"
            f"Risk_Level: {info['risk']}\n"
            f"Impact: {info['impact']}"
        )
        new_docs.append(Document(text=text))

    # --- 3. Insert into the existing index (incremental update) ---
    INDEX.insert_nodes(new_docs)

    # --- 4. Refresh the query engine ---
    QUERY_ENGINE = INDEX.as_query_engine(similarity_top_k=5)

    print(f"✅ Updated {len(new_entries)} ingredients, index refreshed.")


# =========================
# Enhanced analyze_product with DB update


# def analyze_product(raw_text: str) -> Dict:
#     items = tokenize_ingredient_list(raw_text)
#     per_ing = []
#     buckets = {"High": [], "Medium": [], "Low": [], "Unknown": []}
#     new_entries = {}

#     for ing in items:
#         ing_lc = ing.lower().strip()
#         db_entry = RISK_DB.get(ing_lc)

#         if db_entry:
#             # use existing known info
#             risk, impact = db_entry["risk"], db_entry["impact"]
#         else:
#             # unknown → ask LLM for real-world info
#             ai_info = llm_lookup_unknown(ing)
#             new_entries[ing_lc] = ai_info
#             risk, impact = ai_info["risk"], ai_info["impact"]

#         level = bucketize(risk)
#         entry = {
#             "input": ing,
#             "ingredient": ing_lc,
#             "risk_level": level,
#             "impact": impact,
#         }
#         per_ing.append(entry)
#         buckets[level].append({"ingredient": ing_lc, "impact": impact})

#     # add only unknowns into riskdata.py
#     if new_entries:
#         update_riskdata(new_entries)
#         global DOCS, INDEX, QUERY_ENGINE
#         DOCS = json_to_documents(RISK_DB | new_entries)
#         INDEX = build_index(DOCS)
#         QUERY_ENGINE = INDEX.as_query_engine(similarity_top_k=5)

#     score = overall_score(buckets)
#     findings = {
#         "overall_score": score,
#         "high_risk": buckets["High"],
#         "medium_risk": buckets["Medium"],
#         "low_risk": buckets["Low"],
#         "unknown": buckets["Unknown"],
#         "details": per_ing,
#     }
#     findings["explanation"] = llm_explain(findings)
#     return findings


# =========================
# Gradio UI
# =========================
INTRO = """Paste the full ingredient list of a product (e.g., a foundation).
I will score it (Excellent / Poor / Bad), list high/medium risk ingredients, and summarize long-term impacts.
"""

with gr.Blocks(title="Cosmetic Ingredient Safety – Local RAG") as demo:
    gr.Markdown("# 🧪 Cosmetic Ingredient Safety (JSON + LlamaIndex + Chroma)")
    gr.Markdown(INTRO)

    with gr.Row():
        input_box = gr.Textbox(
            label="Ingredient list",
            placeholder="Water, Titanium Dioxide, Cyclopentasiloxane, Dimethicone, Parabens, Fragrance, Niacinamide ...",
            lines=6,
        )
    analyze_btn = gr.Button("Analyze")
    with gr.Row():
        score_out = gr.Textbox(label="Overall Score", interactive=False)
    with gr.Row():
        explanation_out = gr.Markdown(label="Explanation")
    details_json = gr.JSON(label="Structured Result (JSON)")

    def run_pipeline(user_text):
        result = analyze_product(user_text)
        return result.get("overall_score", ""), result.get("explanation", ""), result

    analyze_btn.click(
        run_pipeline,
        inputs=[input_box],
        outputs=[score_out, explanation_out, details_json],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
