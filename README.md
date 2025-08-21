
# 🧴 Ingredient Risk Analyzer

The **Ingredient Risk Analyzer** helps consumers and researchers evaluate the safety of cosmetic and skincare products by analyzing ingredient lists.  
It supports both **image uploads** (OCR extraction) and **product URLs**, and provides a detailed risk breakdown of each ingredient using a local knowledge base (LlamaIndex + ChromaDB).

---

## 🚀 Features
- 📸 **Image Upload**: Drag & drop a product ingredient list image → OCR extracts text → Ingredients are analyzed.
- 🔗 **URL Input**: Paste a product page link (e.g., Sephora, Clinique) → Automatically scrape and analyze ingredient list.
- 🧠 **Smart Extraction**: Local LLM extracts only ingredients, filtering out non-ingredient text/noise.
- 📊 **Risk Scoring**: Ingredients categorized into:
  - **High Risk** (e.g., parabens, talc, BHT)
  - **Medium Risk** (e.g., aluminum salts, PEGs)
  - **Low Risk / Safe** (commonly used ingredients)
- 📝 **Explanations**: Each ingredient includes its **risk level** and **impact** (e.g., irritation, toxicity, bioaccumulation).
- 🔒 **Local & Private**: Uses **LlamaIndex + ChromaDB** for local processing, no external API calls required.

---

## 🛠 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/cosmetic-ingredient-risk-analyzer.git
cd ingredient-risk-analyzer
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate   # On Mac/Linux
venv\Scripts\activate      # On Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the app
```bash
python3 app.py
```

---

## 🧪 Example Use Cases
- Upload a photo of Clinique foundation → Extracts and rates all ingredients.
- Paste a Sephora product URL → Scrapes and analyzes the listed ingredients.
- Get a breakdown of risks (e.g., parabens flagged as medium risk, talc flagged as high risk).
