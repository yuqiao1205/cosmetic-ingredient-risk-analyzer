# 🧴 Cosmetic Ingredient Risk Analyzer

The Cosmetic Ingredient Risk Analyzer helps consumers and researchers evaluate the safety of cosmetic and skincare products by analyzing ingredient lists.  
It supports **image uploads**, **product URLs**, and **manual pasted ingredient lists**, and provides a detailed risk breakdown of each ingredient using a local knowledge base (**LlamaIndex + ChromaDB + Ollama LLM**).

---

## 🚀 Features
- 📸 **Image Upload**: Upload a photo of a product’s ingredient list → OCR extracts text → Ingredients are analyzed.
- 🔗 **URL Input**: Paste a product page link (e.g., Sephora, Clinique) → Automatically scrape and analyze ingredients.
- 📋 **Manual Input**: Paste ingredient lists directly for instant analysis.
- 🧠 **Smart Extraction**: Local LLM extracts only ingredients, filtering out non-ingredient text.
- 🏷 **Product Scoring**: Rates the overall safety of the product.
- 📊 **Risk Scoring**: Ingredients categorized into:
  - **High Risk** (e.g., parabens, talc, BHT)
  - **Medium Risk** (e.g., aluminum salts, PEGs)
  - **Low Risk / Safe** (commonly used ingredients)
- 📝 **Explanations**: Each ingredient includes **risk level** + **impact** (e.g., irritation, toxicity, bioaccumulation).
- 🔒 **Local & Private**: Uses **LlamaIndex + ChromaDB + Ollama** for local processing. No external API calls required.

---

## 🛠 Tech Stack

- **Backend**: Python
- **Frontend**: Gradio

- **OCR**: Tesseract (via pytesseract) 

- **LLM Integration**: LlamaIndex + Ollama (local models)

- **Vector Database**: ChromaDB

---

## 🛠 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/yuqiao1205/cosmetic-ingredient-risk-analyzer.git
cd cosmetic-ingredient-risk-analyzer
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate   # On Mac/Linux
venv\Scripts\activate      # On Windows
```

### 3. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Ollama
Ollama is required to run the local LLM.

- **Mac/Linux**:  
  [Download & Install Ollama](https://ollama.ai/download)

- **Windows**:  
  Follow setup instructions from [Ollama for Windows](https://ollama.ai/download/windows)

### 5. Pull Local LLM (Gemma 3)
After installing Ollama, pull the **Gemma 3** model (or another supported LLM):
```bash
ollama pull gemma3:4b
```

### 6. Start the Local LLM
Before running the app, make sure Ollama is running:
```bash
ollama run gemma3:4b
```

### 7. Run the App
In another terminal, start the app:
```bash
python3 app.py
```

---

## 🧪 Example Use Cases
- 📸 Upload a **photo of Clinique foundation** → Extracts and rates all ingredients.
- 🔗 Paste a **Sephora product URL** → Scrapes and analyzes the ingredient list.
- 📋 Copy-paste **ingredients directly** → Instantly get a breakdown of risks.
- 📊 Get categorized reports (e.g., parabens = medium risk, talc = high risk).

---

✅ Now your **Ingredient Risk Analyzer** runs fully offline with local OCR, LlamaIndex, ChromaDB, and Ollama-powered LLM.

## 📌 Note
1. Please make sure that Tesseract is correctly installed on your system. You can check by running tesseract --version in the terminal. If it’s not installed, use:

brew install tesseract

2. Before running the application, you must first run the local LLM (gemma3:4b) or component extraction and analysis will not be possible.

