User pastes in a makeup product’s ingredients list (like Clinique foundation).
• System scores the product (e.g. Excellent / Poor / Bad).
• Shows which ingredients are high risk, medium risk, and explains the impact.
• Uses LlamaIndex + Chroma (local) with a small knowledge base (like EWG or Open Beauty Facts).
 Using the LLM to extract the ingredients after OCR will make the process much more robust and less susceptible to the noise and non-ingredient text often found on product labels.

I’ll give you a working skeleton you can run locally with Python:
