# Dafinitiq AI application: draft answers

Edit these in your own words before submitting.

## Give your product a name

Awaz Order: AI Order Desk for Pakistani Distributors

## Describe your AI product (min 200 characters)

Awaz Order turns WhatsApp voice notes into confirmed orders and credit records for distributors and wholesalers in Pakistan. Shopkeepers already order by voice note in Urdu, Punjabi or English ("bhai 2 carton Shan biryani masala, 5 tin Dalda, udhaar likh do"), and staff write each one down by hand, causing delays, wrong items and lost credit records. Awaz Order transcribes the voice note, extracts the items and quantities, matches them to the distributor's catalogue and prices, highlights anything uncertain with "did you mean…?" suggestions, creates the order, updates the shop's khata (credit ledger) and generates a WhatsApp-ready confirmation in Urdu with the balance due. It is for small and mid-size FMCG distributors, wholesalers and their order-takers. Open-source tools and models: Whisper large-v3 for Urdu/Punjabi speech-to-text, Qwen and gpt-oss (open-weight LLMs) for catalogue-constrained structured extraction, RapidFuzz for multilingual catalogue matching, FastAPI and SQLite/PostgreSQL. It is built to keep working under load: cached sample orders, a model fallback chain, and an offline rule-based parser if every AI service is unavailable. Next: WhatsApp Business API integration, Whisper fine-tuning on Punjabi voice notes, reorder forecasting and credit scoring from ledger history.

## Why did you choose this idea? (min 100 characters)

DRAFT: replace with your real reason and personal connection.

Pakistani trade runs on WhatsApp voice notes, yet every order is still typed by hand by someone replaying the note again and again. I build lead and form pipelines for businesses professionally and have seen how much revenue is lost when incoming requests are missed or recorded wrongly. Most AI tools ignore Urdu and Punjabi speakers and the way small businesses actually work. Awaz Order fits their existing habit instead of forcing a new app, saves money they can measure (fewer wrong orders, faster dispatch, accurate credit records) and grows naturally into forecasting and credit scoring.

## Architecture diagram

Upload `docs/architecture.mmd` (check it renders at https://mermaid.live first).

## MVP link

- URL: <your Render / Hugging Face URL>
- Demo login: demo@awazorder.pk / Demo@1234
- Tip for reviewers: "Try a sample order" works instantly; you can also record a voice note in Urdu/Punjabi or type an order.
