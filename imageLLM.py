import os
import re
import json
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv

import chromadb
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from PIL import Image

#  pip install pytesseract to system
# brew install pytesseract
import pytesseract


# Install this library if you haven't: pip install opencv-python
import cv2
import numpy as np

import gradio as gr
from riskdata import RISK_DB  # our JSON-style dataset

# =========================
# Config & Setup
# =========================

# Configure local LLM (Gemma 2:4b)
llm = Ollama(model="gemma3:4b", request_timeout=120.0)
Settings.llm = llm

# Configure local embedding model (nomic-embed-text)
embed_model = OllamaEmbedding(model_name="nomic-embed-text")
Settings.embed_model = embed_model

CHROMA_PATH = "./chroma_db"

# =========================
# OCR Functionality
# =========================

def ocr_from_image(image_path: str) -> str:
    """
    Performs OCR on an image file to extract text.
    Handles potential preprocessing for better OCR results.
    """
    try:
        # Load image with PIL for pytesseract
        image = Image.open(image_path)
        
        # Convert PIL image to a format for OpenCV to potentially improve OCR results
        # A simple preprocessing step might be to convert to grayscale and apply thresholding
        np_image = np.array(image)
        if len(np_image.shape) > 2:
            gray = cv2.cvtColor(np_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = np_image
        
        # Apply a binary threshold to make text stand out
        # This can be adjusted based on image quality
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        # Use pytesseract to extract text from the processed image
        # 'eng' for English language, add 'cos' if a cosmetic-specific model is available
        # You may need to install language packs for pytesseract
        text = pytesseract.image_to_string(thresh, lang='eng')
        
        return text
    except Exception as e:
        print(f"Error during OCR: {e}")
        return ""

# =========================
# LLM-based Ingredient Extraction
# =========================

def extract_ingredients_with_llm(text: str) -> str:
    """
    Uses the local LLM to extract only the cosmetic ingredients from a block of text.
    """
    prompt = f"""
    You are a highly specialized information extraction bot. Your task is to extract a list of only the cosmetic or skincare ingredients from the provided text.
    The ingredients are typically listed after keywords like 'INGREDIENTS:', 'Ingredients:', 'Composition:', or similar.
    
    Rules:
    - Return a single, comma-separated string of the ingredients.
    - Do NOT include any other text, numbers, or non-ingredient words.
    - The output must be a clean list of ingredients, e.g., "Water, Glycerin, Butylene Glycol, Niacinamide, Sodium Hyaluronate"
    - If no ingredients are found, return an empty string.

    Text to analyze:
    ---
    {text}
    ---
    
    Extracted ingredients list:
    """
    
    try:
        response = llm.complete(prompt)
        extracted_text = str(response).strip()
        # Clean up any potential LLM conversational fluff or unwanted characters
        extracted_text = re.sub(r'^(?:\s*["\']?|\s*list\s*of\s*ingredients\s*:\s*|\s*extracted\s*ingredients\s*:\s*)', '', extracted_text, flags=re.IGNORECASE)
        extracted_text = re.sub(r'["\']?\s*$', '', extracted_text).strip()
        return extracted_text
    except Exception as e:
        print(f"Error during LLM ingredient extraction: {e}")
        return ""


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
    
    # Use a different collection name for local embeddings to avoid dimension mismatch
    collection_name = "ingredients_local"
    
    # Delete existing collection if it exists to avoid dimension conflicts
    # try:
    #     client.delete_collection(collection_name)
    #     print(f"Deleted existing collection: {collection_name}")
    # except Exception:
    #     pass  # Collection doesn't exist, which is fine
    
    # collection = client.create_collection(collection_name)
    collection = client.get_or_create_collection(collection_name)
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
- Only write cautionary notes for high or medium risk ingredients.
- Write a concise, user-friendly explanation.
- For High risk: include likely long-term impacts in 1 short sentence each.
- If it shows Medium risk please include brief caution,otherwise no need to mention.

- End with a one-sentence overall rationale that matches the score.
Keep it to ~5 bulleted lines total.
JSON:
{json_payload}
"""


def llm_explain(findings: Dict) -> str:
    payload = json.dumps(findings, ensure_ascii=False, indent=2)
    resp = QUERY_ENGINE.query(EXPLANATION_PROMPT.format(json_payload=payload))
    return str(resp)


def analyze_product(raw_text: str) -> Dict:
    global RISK_DB  # Need to access the global RISK_DB for updates

    items = tokenize_ingredient_list(raw_text)
    per_ing = []
    buckets = {"High": [], "Medium": [], "Low": [], "Unknown": []}
    new_entries = {}

    for ing in items:
        ing_lc = ing.lower().strip()
        db_entry = RISK_DB.get(ing_lc)

        if db_entry:
            # Use existing ingredient data - no LLM call needed
            risk, impact = db_entry["risk"], db_entry["impact"]
            print(f"✅ Found existing ingredient: {ing_lc}")
        else:
            # Only lookup truly unknown ingredients via LLM
            print(f"🔍 Looking up new ingredient: {ing_lc}")
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

    # Only update riskdata.py and index if we have truly new ingredients
    if new_entries:
        print(f"📝 Updating database with {len(new_entries)} new ingredients...")
        update_riskdata(new_entries)

        # Update the global RISK_DB to include new entries for future lookups
        RISK_DB.update(new_entries)

        # Only embed new ingredient docs to the index
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
        print(f"✅ Database and index updated successfully!")
    else:
        print("✅ All ingredients already in database - no updates needed")

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
    Ask LLM for risk + impact with detailed, ingredient-specific information.
    Ensures each ingredient gets a unique, meaningful description.
    """
    # Enhanced prompt with more specific instructions
    prompt = f"""You are a cosmetic safety expert with extensive knowledge of cosmetic ingredients.

Ingredient: {ingredient}

Please provide:
1. Risk level: Classify as exactly one of: High, Medium, Low
2. Impact: A detailed, factual description of this specific ingredient's properties, benefits, and potential concerns in less than 20 words. 

Requirements:
- Be specific to THIS ingredient - research its actual chemical properties and cosmetic uses
- Include what the ingredient does in cosmetics (moisturizer, preservative, emulsifier, etc.)
- Mention any known benefits or concerns specific to this ingredient
- Use real cosmetic science knowledge, not generic statements
- Minimum 10 words for impact description
- Never use "Unknown", "Not available", or generic fallback phrases

Examples of good responses:
- "phenoxyethanol:Preservative; can cause skin irritation, allergic reactions, toxic at high doses"
- "Silicone-based emollient that creates smooth application and water resistance; may cause buildup on hair but considered safe for skin use."

Format as JSON with keys 'risk' and 'impact' only."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = llm.complete(prompt)
            data = json.loads(str(resp).strip())

            risk = data.get("risk", "").strip().capitalize()
            impact = data.get("impact", "").strip()

            # Validate response quality
            if (
                risk in ["High", "Medium", "Low"]
                and impact
                and len(impact) >= 20
                and "unknown" not in impact.lower()
                and "not available" not in impact.lower()
                and "no known risks" not in impact.lower()
            ):
                return {"risk": risk, "impact": impact}

            # If validation fails, enhance the prompt for retry
            if attempt < max_retries - 1:
                prompt += f"\n\nPrevious attempt was too generic. Please provide specific information about {ingredient}'s actual cosmetic function and properties."

        except (json.JSONDecodeError, Exception) as e:
            if attempt < max_retries - 1:
                continue

    # Enhanced fallback with ingredient-specific research attempt
    fallback_prompt = f"""Research the cosmetic ingredient '{ingredient}' and provide its primary function and safety profile in less than 20 words. Focus on what this ingredient specifically does in cosmetics."""

    try:
        fallback_resp = llm.complete(fallback_prompt)
        fallback_text = str(fallback_resp).strip()
        if len(fallback_text) >= 20:
            return {"risk": "Low", "impact": fallback_text}
    except:
        pass

    # Final ingredient-specific fallback based on common cosmetic ingredient patterns
    ingredient_lower = ingredient.lower()
    if any(term in ingredient_lower for term in ["acid", "aha", "bha"]):
        impact = f"Chemical exfoliant {ingredient} that helps remove dead skin cells; may cause irritation or sensitivity, especially with sun exposure."
        risk = "Medium"
    elif any(term in ingredient_lower for term in ["oil", "butter", "wax"]):
        impact = f"Natural emollient {ingredient} that provides moisturizing and conditioning properties; generally well-tolerated but may cause comedogenic effects in acne-prone skin."
        risk = "Low"
    elif any(term in ingredient_lower for term in ["glycol", "glycerin"]):
        impact = f"Humectant {ingredient} that attracts and retains moisture in the skin; typically safe but may cause mild irritation in very sensitive individuals."
        risk = "Low"
    elif any(term in ingredient_lower for term in ["silicone", "dimethicone", "cyclo"]):
        impact = f"Silicone-based ingredient {ingredient} that provides smooth texture and protective barrier; generally safe but may cause buildup with prolonged use."
        risk = "Low"
    elif any(term in ingredient_lower for term in ["paraben", "preservative"]):
        impact = f"Preservative {ingredient} that prevents microbial growth in cosmetics; some concerns about potential endocrine disruption with long-term use."
        risk = "Medium"
    else:
        impact = f"Cosmetic ingredient {ingredient} used for formulation purposes; specific safety profile requires individual assessment based on concentration and usage."
        risk = "Low"

    return {"risk": risk, "impact": impact}


# =========================
# Riskdata updater

RISKDATA_FILE = Path("riskdata.py")


def update_riskdata(new_entries: dict):
    """
    Efficiently update risk_data.py with only new ingredients.
    Only writes to file and updates index when truly necessary.
    """
    global QUERY_ENGINE, INDEX

    if not new_entries:
        print("⚠️ No new entries to update")
        return

    print(f"📝 Writing {len(new_entries)} new ingredients to riskdata.py...")

    # --- 1. Read current file and merge with new entries ---
    try:
        # Read current riskdata.py to get the latest state
        current_content = RISKDATA_FILE.read_text()
        # Extract current RISK_DB from file (more reliable than using global)
        exec(current_content, {"RISK_DB": {}})
        current_db = locals().get("RISK_DB", RISK_DB)
    except:
        # Fallback to global RISK_DB if file read fails
        current_db = RISK_DB

    # Merge only truly new entries
    updated_db = {**current_db, **new_entries}

    # --- 2. Write updated database to file ---
    content = "RISK_DB = " + json.dumps(updated_db, indent=4) + "\n"
    RISKDATA_FILE.write_text(content)
    print(f"✅ Successfully wrote {len(new_entries)} new ingredients to riskdata.py")

    # --- 3. Only create documents for new entries (not entire database) ---
    new_docs = []
    for ingredient, info in new_entries.items():
        text = (
            f"Ingredient: {ingredient}\n"
            f"Risk_Level: {info['risk']}\n"
            f"Impact: {info['impact']}"
        )
        new_docs.append(Document(text=text))

    # --- 4. Incrementally add only new documents to existing index ---
    if new_docs:
        INDEX.insert_nodes(new_docs)
        QUERY_ENGINE = INDEX.as_query_engine(similarity_top_k=5)
        print(f"✅ Added {len(new_docs)} new documents to search index")

    print(f"🎉 Database update complete! Total ingredients now: {len(updated_db)}")


# =========================
# Gradio UI
# =========================
INTRO = """Paste the full ingredient list of a product (e.g., a foundation) or upload a photo of the ingredients.
I will score it (Excellent / Poor / Bad), list high/medium risk ingredients, and summarize long-term impacts.
Running completely locally with Gemma 2:4b and nomic-embed-text - no OpenAI API required!
"""

with gr.Blocks(title="Cosmetic Ingredient Safety – Local RAG") as demo:
    gr.Markdown("# 🧪 Cosmetic Ingredient Safety (Local Models + LlamaIndex + Chroma)")
    gr.Markdown(INTRO)

    with gr.Row():
        with gr.Column(scale=1):
            input_box = gr.Textbox(
                label="Ingredient list (text input)",
                placeholder="Water, Titanium Dioxide, Cyclopentasiloxane, Dimethicone, Parabens, Fragrance, Niacinamide ...",
                lines=6,
            )
            analyze_text_btn = gr.Button("Analyze Text")
        with gr.Column(scale=1):
            image_input = gr.Image(type="filepath", label="Upload image of ingredients")
            analyze_image_btn = gr.Button("Analyze Image")

    with gr.Row():
        score_out = gr.Textbox(label="Overall Score", interactive=False)
    with gr.Row():
        explanation_out = gr.Markdown(label="Explanation")
    details_json = gr.JSON(label="Structured Result (JSON)")

    def run_pipeline_text(user_text):
        if not user_text:
            return "", "Please enter an ingredient list.", None
        result = analyze_product(user_text)
        return result.get("overall_score", ""), result.get("explanation", ""), result

    def run_pipeline_image(image_path):
        if not image_path:
            return "", "Please upload an image.", None
        
        # 1. Perform OCR
        raw_text = ocr_from_image(image_path)
        if not raw_text:
            return "", "Could not extract text from the image. Please try a clearer image.", None
        
        # 2. Use LLM to extract a clean list of ingredients from the OCR text
        ingredients_list_text = extract_ingredients_with_llm(raw_text)
        if not ingredients_list_text:
            return "", "Could not extract a valid list of ingredients from the text. Please ensure the ingredients are clearly visible.", None
        
        # 3. Pass the extracted text to the analysis pipeline
        result = analyze_product(ingredients_list_text)
        return result.get("overall_score", ""), result.get("explanation", ""), result

    analyze_text_btn.click(
        run_pipeline_text,
        inputs=[input_box],
        outputs=[score_out, explanation_out, details_json],
    )

    analyze_image_btn.click(
        run_pipeline_image,
        inputs=[image_input],
        outputs=[score_out, explanation_out, details_json],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)