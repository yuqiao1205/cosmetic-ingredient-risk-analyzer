Ingredient Risk Analyzer is a local Python application that helps users evaluate cosmetic and skincare products.
It allows users to upload an image (e.g., product packaging) or input a URL to analyze the ingredients list.
Using OCR + a local LLM (via LlamaIndex + ChromaDB), the system extracts cosmetic ingredients, checks them against a small knowledge base (e.g., EWG, Open Beauty Facts), and provides:

✅ A product score (Excellent / Medium / Poor)

⚠️ A breakdown of high-risk and medium-risk ingredients

📖 Explanations of each ingredient’s potential health impact

This approach makes the analysis robust against noisy product labels and marketing text.

Features
📷 Image Upload: Drag & drop a product photo to extract ingredients via OCR.

🌐 URL Input: Enter a product page URL to fetch and analyze the ingredient list.

🧠 Ingredient Extraction: Local LLM ensures clean parsing of ingredient names.

📊 Risk Analysis: Highlights high- and medium-risk ingredients with explanations.

🏷 Product Scoring: Rates the overall safety of the product.

💾 Local Knowledge Base: Uses ChromaDB + curated datasets (EWG, Open Beauty Facts).

Tech Stack
Backend: Python 
Frontend: Gradio

OCR: Tesseract (via pytesseract)

LLM Integration: LlamaIndex + Ollama (local models)

Vector Database: ChromaDB

