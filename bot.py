Щоб автоматичний аналіз (auto-analysis) повністю відключився для валютних пар (forex) і акцій (stocks), потрібно прибрати або заблокувати виклики функції rank_assets_for_api() для цих типів активів.

🔧 Що конкретно прибрати:
У файлі bot.py, в маршрут /api/get_active_markets, заміни ось цей фрагмент:

python
Копіювати
Редагувати
    ranked_stocks = rank_assets_for_api(STOCK_TICKERS, 'stocks')
    top_stocks = [p['ticker'] for p in ranked_stocks[:5]]
    all_forex_pairs = list(FOREX_PAIRS_MAP.keys())
    ranked_forex = rank_assets_for_api(all_forex_pairs, 'forex')
    top_forex = [p['ticker'] for p in ranked_forex[:5]]
на такий:

python
Копіювати
Редагувати
    top_stocks = []
    top_forex = []
І повністю забери виклики rank_assets_for_api() для акцій і форексу.

🔻 ОНОВЛЕНИЙ РОЗДІЛ /api/get_active_markets:
python
Копіювати
Редагувати
@app.route("/api/get_active_markets", methods=["GET"])
def api_get_active_markets():
    try:
        ranked_crypto = rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto')
        top_crypto = [p['ticker'] for p in ranked_crypto[:5]]

        # Відключаємо автоаналіз для stocks і forex
        top_stocks = []
        top_forex = []

        return jsonify({
            "active_crypto": top_crypto,
            "active_stocks": top_stocks,
            "active_forex": top_forex
        })
    except Exception as e:
        logger.error(f"API error for active markets: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при аналізі ринків"}), 500
✅ Результат:
Crypto аналізується автоматично (залишається).

Forex і Stocks не передаються через rank_assets_for_api, не вантажать API, і не кешуються.

На фронтенді при цьому залишаються статичні списки форексу та акцій (через /api/get_ranked_pairs), як і потрібно.

