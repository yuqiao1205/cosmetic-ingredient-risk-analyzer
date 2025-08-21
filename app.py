import os
import re
import json
import random
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from PIL import Image
import pytesseract
import cv2
import numpy as np
import gradio as gr
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from riskdata import RISK_DB

# =========================
# Config & Setup
# =========================
llm = Ollama(model="gemma3:4b", request_timeout=120.0) # use your local LLM here if you want to download a different local LLM
Settings.llm = llm
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
        image = Image.open(image_path)
        np_image = np.array(image)
        if len(np_image.shape) > 2:
            gray = cv2.cvtColor(np_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = np_image
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(thresh, lang='eng')
        return text
    except Exception as e:
        print(f"Error during OCR: {e}")
        return ""

# =========================
# Web Scraping Functionality (New)
# =========================
# List of common user agents to rotate through
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
]

def scrape_ingredients_from_url(url: str) -> str:
    """
    Fetches the content of a URL using a headless Selenium browser and attempts
    to extract cosmetic ingredients. This method handles JavaScript-rendered pages.
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    random_user_agent = random.choice(USER_AGENTS)
    options.add_argument(f"user-agent={random_user_agent}")

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait_time = 20
        driver.set_page_load_timeout(wait_time)

        print(f"Loading {url} with Selenium...")
        driver.get(url)

        WebDriverWait(driver, wait_time).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        
        potential_ingredients_sections = soup.find_all(
            lambda tag: tag.name in ['div', 'p', 'span', 'li', 'ul'] and 
            any(keyword in tag.get_text(strip=True).lower() for keyword in ['ingredients', 'composition', 'what\'s in it', 'full list'])
        )
        
        ingredient_text = ""
        for section in potential_ingredients_sections:
            text = section.get_text(separator=' ', strip=True)
            if len(text.split(',')) > 5 and "ingredients" in text.lower():
                ingredient_text = text
                break
        
        if not ingredient_text:
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if 'description' in data and 'ingredients' in data['description'].lower():
                        ingredient_text = data['description']
                        break
                    elif 'ingredients' in data:
                        ingredient_text = data['ingredients']
                        break
                    elif 'product' in data and 'description' in data['product'] and 'ingredients' in data['product']['description'].lower():
                        ingredient_text = data['product']['description']
                        break
                except json.JSONDecodeError:
                    continue

        if not ingredient_text:
            print(f"Could not find a clear ingredient list on {url}. Trying a more generic search.")
            body_text = soup.body.get_text(separator=' ', strip=True)
            match = re.search(r'(ingredients|composition|what\'s in it):?\s*([A-Z][a-zA-Z\s,.-]+(?:\s*(?:,\s*[A-Z][a-zA-Z\s,.-]+)+)?)', body_text, re.IGNORECASE)
            if match:
                ingredient_text = match.group(2)
            else:
                return "No ingredient list found on this page using common patterns. Please provide the text manually."
        
        return ingredient_text

    except TimeoutException:
        print(f"Timeout: Page took longer than {wait_time} seconds to load.")
        return f"Error: Timeout. Page took longer than {wait_time} seconds to load. Try again or provide text manually."
    except WebDriverException as e:
        print(f"WebDriver error: {e}")
        return f"Error: WebDriver failed to run. Ensure Chrome is installed and updated. ({e})"
    except Exception as e:
        print(f"An unexpected error occurred during scraping: {e}")
        return f"An unexpected error occurred during scraping: {e}"
    finally:
        if driver:
            driver.quit()

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
    collection_name = "ingredients_local"
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

- End with two or three sentences overall rationale that matches the score.
Keep it to ~5 bulleted lines total.
JSON:
{json_payload}
"""

def llm_explain(findings: Dict) -> str:
    payload = json.dumps(findings, ensure_ascii=False, indent=2)
    resp = QUERY_ENGINE.query(EXPLANATION_PROMPT.format(json_payload=payload))
    return str(resp)

def analyze_product(raw_text: str) -> Dict:
    global RISK_DB
    items = tokenize_ingredient_list(raw_text)
    per_ing = []
    buckets = {"High": [], "Medium": [], "Low": [], "Unknown": []}
    new_entries = {}
    for ing in items:
        ing_lc = ing.lower().strip()
        db_entry = RISK_DB.get(ing_lc)
        if db_entry:
            risk, impact = db_entry["risk"], db_entry["impact"]
            print(f"✅ Found existing ingredient: {ing_lc}")
        else:
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
    if new_entries:
        print(f"📝 Updating database with {len(new_entries)} new ingredients...")
        update_riskdata(new_entries)
        RISK_DB.update(new_entries)
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
            if (
                risk in ["High", "Medium", "Low"]
                and impact
                and len(impact) >= 20
                and "unknown" not in impact.lower()
                and "not available" not in impact.lower()
                and "no known risks" not in impact.lower()
            ):
                return {"risk": risk, "impact": impact}
            if attempt < max_retries - 1:
                prompt += f"\n\nPrevious attempt was too generic. Please provide specific information about {ingredient}'s actual cosmetic function and properties."
        except (json.JSONDecodeError, Exception) as e:
            if attempt < max_retries - 1:
                continue
    fallback_prompt = f"""Research the cosmetic ingredient '{ingredient}' and provide its primary function and safety profile in less than 20 words. Focus on what this ingredient specifically does in cosmetics."""
    try:
        fallback_resp = llm.complete(fallback_prompt)
        fallback_text = str(fallback_resp).strip()
        if len(fallback_text) >= 20:
            return {"risk": "Low", "impact": fallback_text}
    except:
        pass
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
# =========================
RISKDATA_FILE = Path("riskdata.py")
def update_riskdata(new_entries: dict):
    global QUERY_ENGINE, INDEX
    if not new_entries:
        print("⚠️ No new entries to update")
        return
    print(f"📝 Writing {len(new_entries)} new ingredients to riskdata.py...")
    try:
        current_content = RISKDATA_FILE.read_text()
        exec(current_content, {"RISK_DB": {}})
        current_db = locals().get("RISK_DB", RISK_DB)
    except:
        current_db = RISK_DB
    updated_db = {**current_db, **new_entries}
    content = "RISK_DB = " + json.dumps(updated_db, indent=4) + "\n"
    RISKDATA_FILE.write_text(content)
    print(f"✅ Successfully wrote {len(new_entries)} new ingredients to riskdata.py")
    new_docs = []
    for ingredient, info in new_entries.items():
        text = (
            f"Ingredient: {ingredient}\n"
            f"Risk_Level: {info['risk']}\n"
            f"Impact: {info['impact']}"
        )
        new_docs.append(Document(text=text))
    if new_docs:
        INDEX.insert_nodes(new_docs)
        QUERY_ENGINE = INDEX.as_query_engine(similarity_top_k=5)
        print(f"✅ Added {len(new_docs)} new documents to search index")
    print(f"🎉 Database update complete! Total ingredients now: {len(updated_db)}")

# =========================
# Gradio UI
# =========================
INTRO = """Paste the full ingredient list of a product (e.g., a foundation) or upload a photo of the ingredients, or provide a URL to a product page.
I will score it (Excellent / Poor / Bad), list high/medium risk ingredients, and summarize long-term impacts.
Running completely locally with Gemma3:4b and nomic-embed-text - no OpenAI or external API required!
"""
def format_findings_for_display(findings: dict) -> str:
    """Formats the analysis findings into a human-readable Markdown string."""
    output = "### Ingredient Breakdown\n\n"
    
    # Organize ingredients by risk level
    high_risk = sorted(findings.get('high_risk', []), key=lambda x: x['ingredient'])
    medium_risk = sorted(findings.get('medium_risk', []), key=lambda x: x['ingredient'])
    low_risk = sorted(findings.get('low_risk', []), key=lambda x: x['ingredient'])
    unknown_risk = sorted(findings.get('unknown', []), key=lambda x: x['ingredient'])

    if high_risk:
        output += "#### 🔴 High Risk\n"
        for item in high_risk:
            output += f"- **{item['ingredient'].capitalize()}**: {item['impact']}\n"
        output += "\n"

    if medium_risk:
        output += "#### 🟡 Medium Risk\n"
        for item in medium_risk:
            output += f"- **{item['ingredient'].capitalize()}**: {item['impact']}\n"
        output += "\n"

    if low_risk:
        output += "#### 🟢 Low Risk\n"
        for item in low_risk:
            output += f"- **{item['ingredient'].capitalize()}**: {item['impact']}\n"
        output += "\n"
    
    if unknown_risk:
        output += "#### ⚪ Unknown Risk\n"
        for item in unknown_risk:
            output += f"- **{item['ingredient'].capitalize()}**: {item['impact']}\n"
        output += "\n"

    if not any([high_risk, medium_risk, low_risk, unknown_risk]):
        output += "No ingredients were found or analyzed in this text.\n"

    return output


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
        with gr.Column(scale=1):
            url_input = gr.Textbox(
                label="Product Page URL",
                placeholder="e.g., https://www.aaa.com/us/skincare/categories/cleansers/soy-face-cleanser.html",
                lines=3
            )
            analyze_url_btn = gr.Button("Analyze URL")
    with gr.Row():
        score_out = gr.Textbox(label="Overall Score", interactive=False)
    with gr.Row():
        explanation_out = gr.Markdown(label="Explanation")
    # Change from JSON to Markdown
    details_out = gr.Markdown(label="Ingredient Breakdown")

    def run_pipeline_text(user_text):
        if not user_text:
            return "", "Please enter an ingredient list.", ""
        result = analyze_product(user_text)
        formatted_details = format_findings_for_display(result)
        return result.get("overall_score", ""), result.get("explanation", ""), formatted_details

    def run_pipeline_image(image_path):
        if not image_path:
            return "", "Please upload an image.", ""
        raw_text = ocr_from_image(image_path)
        if not raw_text:
            return "", "Could not extract text from the image. Please try a clearer image.", ""
        ingredients_list_text = extract_ingredients_with_llm(raw_text)
        if not ingredients_list_text:
            return "", "Could not extract a valid list of ingredients from the text. Please ensure the ingredients are clearly visible.", ""
        result = analyze_product(ingredients_list_text)
        formatted_details = format_findings_for_display(result)
        return result.get("overall_score", ""), result.get("explanation", ""), formatted_details

    def run_pipeline_url(url):
        if not url:
            return "", "Please enter a URL.", ""
        try:
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                return "", "Invalid URL format. Please enter a complete URL (e.g., https://www.example.com/product).", ""
        except ValueError:
            return "", "Invalid URL format. Please enter a complete URL (e.g., https://www.example.com/product).", ""
        scraped_text = scrape_ingredients_from_url(url)
        if "Error:" in scraped_text or "No ingredient list found" in scraped_text:
            return "", scraped_text, ""
        ingredients_list_text = extract_ingredients_with_llm(scraped_text)
        if not ingredients_list_text:
            return "", "Could not extract a valid list of ingredients from the scraped page. The page structure might be complex or the ingredient list is not clearly identifiable.", ""
        result = analyze_product(ingredients_list_text)
        formatted_details = format_findings_for_display(result)
        return result.get("overall_score", ""), result.get("explanation", ""), formatted_details

    analyze_text_btn.click(
        run_pipeline_text,
        inputs=[input_box],
        outputs=[score_out, explanation_out, details_out],
    )

    analyze_image_btn.click(
        run_pipeline_image,
        inputs=[image_input],
        outputs=[score_out, explanation_out, details_out],
    )

    analyze_url_btn.click(
        run_pipeline_url,
        inputs=[url_input],
        outputs=[score_out, explanation_out, details_out],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)