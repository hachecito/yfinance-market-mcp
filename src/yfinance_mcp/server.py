"""FastMCP server exposing Yahoo Finance market data tools."""

from mcp.server.fastmcp import FastMCP
import yfinance as yf

from .utils import df_to_records, series_to_dict, safe_value

mcp = FastMCP("yfinance")


def _parse_news_article(article: dict) -> dict:
    """Extract news fields from yfinance 1.2+ nested structure.

    Args:
        article: Raw news article dict from yfinance.

    Returns:
        Flattened dict with title, publisher, link, date, summary.
    """
    content = article.get("content", article)
    provider = content.get("provider", {})
    canonical = content.get("canonicalUrl", {})
    click_through = content.get("clickThroughUrl", {})
    return {
        "title": content.get("title", ""),
        "publisher": provider.get("displayName", ""),
        "link": canonical.get("url", "") or click_through.get("url", ""),
        "date": content.get("pubDate", ""),
        "summary": content.get("summary", ""),
    }


# ── Price Tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def get_price_history(
    ticker: str,
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Get OHLCV price history for a ticker.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL").
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max).
        interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo).
        start: Start date string (YYYY-MM-DD). Overrides period if set.
        end: End date string (YYYY-MM-DD).

    Returns:
        dict with ticker and list of OHLCV records.
    """
    try:
        t = yf.Ticker(ticker)
        kwargs = {"interval": interval}
        if start:
            kwargs["start"] = start
            if end:
                kwargs["end"] = end
        else:
            kwargs["period"] = period
        df = t.history(**kwargs)
        return {"ticker": ticker, "data": df_to_records(df)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_dividends(ticker: str) -> dict:
    """Get dividend history for a ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and list of dividend records.
    """
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        return {"ticker": ticker, "data": df_to_records(divs.reset_index().rename(columns={0: "Dividend"}) if not divs.empty else divs)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_splits(ticker: str) -> dict:
    """Get stock split history for a ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and list of split records.
    """
    try:
        t = yf.Ticker(ticker)
        splits = t.splits
        return {"ticker": ticker, "data": df_to_records(splits.reset_index().rename(columns={0: "Split"}) if not splits.empty else splits)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── Info Tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def get_ticker_info(ticker: str) -> dict:
    """Get full company info for a ticker (sector, industry, description, financials, etc.).

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with all available company information.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return {"ticker": ticker, "data": {k: safe_value(v) for k, v in info.items()}}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_fast_info(ticker: str) -> dict:
    """Get quick price snapshot (price, volume, market cap, 52w range).

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with key price metrics.
    """
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        data = {}
        for attr in [
            "currency", "day_high", "day_low", "exchange", "fifty_day_average",
            "last_price", "last_volume", "market_cap", "open", "previous_close",
            "quote_type", "regular_market_previous_close", "shares",
            "ten_day_average_volume", "three_month_average_volume", "timezone",
            "two_hundred_day_average", "year_change", "year_high", "year_low",
        ]:
            try:
                data[attr] = safe_value(getattr(fi, attr, None))
            except Exception:
                pass
        return {"ticker": ticker, "data": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_ticker_summary(ticker: str) -> dict:
    """Get composite summary: fast info + key fundamentals + last 5 news + analyst targets.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with price, fundamentals, news, and analyst target sections.
    """
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price_data = {}
        for attr in ["last_price", "market_cap", "previous_close", "open", "day_high", "day_low", "year_high", "year_low", "fifty_day_average", "two_hundred_day_average"]:
            try:
                price_data[attr] = safe_value(getattr(fi, attr, None))
            except Exception:
                pass

        info = t.info
        fundamentals = {
            k: safe_value(info.get(k))
            for k in ["trailingPE", "forwardPE", "trailingEps", "forwardEps", "dividendYield",
                       "beta", "sector", "industry", "fullTimeEmployees", "shortName"]
            if info.get(k) is not None
        }

        news = []
        try:
            raw_news = t.news[:5] if t.news else []
            for article in raw_news:
                news.append(_parse_news_article(article))
        except Exception:
            pass

        analyst = {}
        try:
            targets = t.analyst_price_targets
            if targets is not None:
                analyst = series_to_dict(targets) if hasattr(targets, "to_dict") else {k: safe_value(v) for k, v in targets.items()} if isinstance(targets, dict) else {}
        except Exception:
            pass

        return {
            "ticker": ticker,
            "price": price_data,
            "fundamentals": fundamentals,
            "news": news,
            "analyst_targets": analyst,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── News Tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def get_ticker_news(ticker: str, count: int = 10) -> dict:
    """Get recent news articles for a ticker.

    Args:
        ticker: Stock ticker symbol.
        count: Number of articles to return (default 10).

    Returns:
        dict with ticker and list of news articles.
    """
    try:
        t = yf.Ticker(ticker)
        raw_news = t.news[:count] if t.news else []
        articles = []
        for article in raw_news:
            articles.append(_parse_news_article(article))
        return {"ticker": ticker, "count": len(articles), "articles": articles}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def search_news(query: str, count: int = 8) -> dict:
    """Search for general market news by keyword.

    Args:
        query: Search query string.
        count: Number of results to return (default 8).

    Returns:
        dict with query and list of news articles.
    """
    try:
        search = yf.Search(query, news_count=count)
        articles = []
        for article in (search.news or []):
            articles.append(_parse_news_article(article))
        return {"query": query, "count": len(articles), "articles": articles}
    except Exception as e:
        return {"error": str(e), "query": query}


# ── Options Tools ────────────────────────────────────────────────────────────


@mcp.tool()
def get_options_expirations(ticker: str) -> dict:
    """Get available options expiration dates for a ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and list of expiration date strings.
    """
    try:
        t = yf.Ticker(ticker)
        return {"ticker": ticker, "expirations": list(t.options)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_options_chain(
    ticker: str,
    expiration: str | None = None,
    option_type: str = "both",
) -> dict:
    """Get options chain data (calls, puts, or both) for a ticker and expiration.

    Args:
        ticker: Stock ticker symbol.
        expiration: Expiration date string (YYYY-MM-DD). Uses nearest if None.
        option_type: "calls", "puts", or "both" (default "both").

    Returns:
        dict with ticker, expiration, and calls/puts data.
    """
    try:
        t = yf.Ticker(ticker)
        if expiration:
            chain = t.option_chain(expiration)
        else:
            exps = t.options
            if not exps:
                return {"error": "No options available", "ticker": ticker}
            chain = t.option_chain(exps[0])
            expiration = exps[0]

        result = {"ticker": ticker, "expiration": expiration}
        if option_type in ("calls", "both"):
            result["calls"] = df_to_records(chain.calls)
        if option_type in ("puts", "both"):
            result["puts"] = df_to_records(chain.puts)
        return result
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── Financial Statements ─────────────────────────────────────────────────────


@mcp.tool()
def get_income_statement(ticker: str, freq: str = "yearly") -> dict:
    """Get income statement for a ticker.

    Args:
        ticker: Stock ticker symbol.
        freq: "yearly", "quarterly", or "trailing".

    Returns:
        dict with ticker and income statement records.
    """
    try:
        t = yf.Ticker(ticker)
        if freq == "quarterly":
            df = t.quarterly_income_stmt
        elif freq == "trailing":
            df = getattr(t, "trailing_income_stmt", t.income_stmt)
        else:
            df = t.income_stmt
        return {"ticker": ticker, "freq": freq, "data": df_to_records(df.T if df is not None else df)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_balance_sheet(ticker: str, freq: str = "yearly") -> dict:
    """Get balance sheet for a ticker.

    Args:
        ticker: Stock ticker symbol.
        freq: "yearly" or "quarterly".

    Returns:
        dict with ticker and balance sheet records.
    """
    try:
        t = yf.Ticker(ticker)
        df = t.quarterly_balance_sheet if freq == "quarterly" else t.balance_sheet
        return {"ticker": ticker, "freq": freq, "data": df_to_records(df.T if df is not None else df)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_cash_flow(ticker: str, freq: str = "yearly") -> dict:
    """Get cash flow statement for a ticker.

    Args:
        ticker: Stock ticker symbol.
        freq: "yearly" or "quarterly".

    Returns:
        dict with ticker and cash flow records.
    """
    try:
        t = yf.Ticker(ticker)
        df = t.quarterly_cashflow if freq == "quarterly" else t.cashflow
        return {"ticker": ticker, "freq": freq, "data": df_to_records(df.T if df is not None else df)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── Analysis & Estimates ─────────────────────────────────────────────────────


@mcp.tool()
def get_analyst_price_targets(ticker: str) -> dict:
    """Get analyst price targets (low, high, mean, median, current).

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and price target data.
    """
    try:
        t = yf.Ticker(ticker)
        targets = t.analyst_price_targets
        if targets is None:
            return {"ticker": ticker, "data": {}}
        if isinstance(targets, dict):
            return {"ticker": ticker, "data": {k: safe_value(v) for k, v in targets.items()}}
        return {"ticker": ticker, "data": series_to_dict(targets)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_recommendations(ticker: str) -> dict:
    """Get analyst buy/sell/hold recommendations over time.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and recommendation records.
    """
    try:
        t = yf.Ticker(ticker)
        recs = t.recommendations
        return {"ticker": ticker, "data": df_to_records(recs)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_upgrades_downgrades(ticker: str) -> dict:
    """Get analyst upgrades and downgrades history.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and upgrade/downgrade records.
    """
    try:
        t = yf.Ticker(ticker)
        ud = t.upgrades_downgrades
        return {"ticker": ticker, "data": df_to_records(ud)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_earnings_estimate(ticker: str) -> dict:
    """Get EPS estimates by period.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and earnings estimate records.
    """
    try:
        t = yf.Ticker(ticker)
        ee = t.earnings_estimate
        return {"ticker": ticker, "data": df_to_records(ee)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_revenue_estimate(ticker: str) -> dict:
    """Get revenue estimates by period.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and revenue estimate records.
    """
    try:
        t = yf.Ticker(ticker)
        re_ = t.revenue_estimate
        return {"ticker": ticker, "data": df_to_records(re_)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_growth_estimates(ticker: str) -> dict:
    """Get growth rate estimates for a ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and growth estimate records.
    """
    try:
        t = yf.Ticker(ticker)
        ge = t.growth_estimates
        return {"ticker": ticker, "data": df_to_records(ge)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_eps_trend(ticker: str) -> dict:
    """Get EPS trend data showing estimate revisions over time.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and EPS trend records.
    """
    try:
        t = yf.Ticker(ticker)
        et = t.eps_trend
        return {"ticker": ticker, "data": df_to_records(et)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── Holders ──────────────────────────────────────────────────────────────────


@mcp.tool()
def get_institutional_holders(ticker: str) -> dict:
    """Get top institutional holders for a ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and institutional holder records.
    """
    try:
        t = yf.Ticker(ticker)
        ih = t.institutional_holders
        return {"ticker": ticker, "data": df_to_records(ih)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_insider_transactions(ticker: str) -> dict:
    """Get recent insider buy/sell transactions.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and insider transaction records.
    """
    try:
        t = yf.Ticker(ticker)
        it = t.insider_transactions
        return {"ticker": ticker, "data": df_to_records(it)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_major_holders(ticker: str) -> dict:
    """Get major holder breakdown (insiders, institutions, etc.).

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and major holder data.
    """
    try:
        t = yf.Ticker(ticker)
        mh = t.major_holders
        return {"ticker": ticker, "data": df_to_records(mh)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── Events & Search ──────────────────────────────────────────────────────────


@mcp.tool()
def get_earnings_dates(ticker: str, limit: int = 12) -> dict:
    """Get upcoming and past earnings dates.

    Args:
        ticker: Stock ticker symbol.
        limit: Number of dates to return (default 12).

    Returns:
        dict with ticker and earnings date records.
    """
    try:
        t = yf.Ticker(ticker)
        ed = t.get_earnings_dates(limit=limit)
        return {"ticker": ticker, "data": df_to_records(ed)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def get_calendar(ticker: str) -> dict:
    """Get upcoming events calendar (dividends, earnings, etc.).

    Args:
        ticker: Stock ticker symbol.

    Returns:
        dict with ticker and calendar event data.
    """
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return {"ticker": ticker, "data": {}}
        if isinstance(cal, dict):
            return {"ticker": ticker, "data": {k: safe_value(v) for k, v in cal.items()}}
        return {"ticker": ticker, "data": series_to_dict(cal)}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def search_tickers(query: str, max_results: int = 8) -> dict:
    """Search for tickers by company name or keyword.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default 8).

    Returns:
        dict with query and list of matching ticker results.
    """
    try:
        search = yf.Search(query, max_results=max_results)
        quotes = []
        for q in (search.quotes or []):
            quotes.append({
                "symbol": q.get("symbol", ""),
                "shortname": q.get("shortname", ""),
                "longname": q.get("longname", ""),
                "exchange": q.get("exchange", ""),
                "quoteType": q.get("quoteType", ""),
            })
        return {"query": query, "count": len(quotes), "results": quotes}
    except Exception as e:
        return {"error": str(e), "query": query}


# ── Sector & Industry ────────────────────────────────────────────────────────


@mcp.tool()
def get_sector_data(sector: str) -> dict:
    """Get sector overview, top companies, top ETFs, and industry breakdown.

    Args:
        sector: Sector key (e.g. "technology", "healthcare", "financial-services",
                "consumer-cyclical", "energy", "industrials", "utilities",
                "basic-materials", "communication-services", "consumer-defensive",
                "real-estate").

    Returns:
        dict with sector overview, top companies, and industries list.
    """
    try:
        s = yf.Sector(sector)
        result = {"sector": sector, "overview": s.overview or {}}
        tc = s.top_companies
        if tc is not None and not tc.empty:
            result["top_companies"] = df_to_records(tc)
        ind = s.industries
        if ind is not None and not ind.empty:
            result["industries"] = df_to_records(ind)
        return result
    except Exception as e:
        return {"error": str(e), "sector": sector}


@mcp.tool()
def get_industry_data(industry: str) -> dict:
    """Get industry overview, top companies, and top growth companies.

    Args:
        industry: Industry key (e.g. "semiconductors", "software-infrastructure",
                  "software-application", "consumer-electronics", "auto-manufacturers").

    Returns:
        dict with industry overview, top companies, and top growth companies.
    """
    try:
        i = yf.Industry(industry)
        result = {
            "industry": industry,
            "overview": i.overview or {},
            "sector": {"key": i.sector_key, "name": i.sector_name},
        }
        tc = i.top_companies
        if tc is not None and not tc.empty:
            result["top_companies"] = df_to_records(tc)
        tg = i.top_growth_companies
        if tg is not None and not tg.empty:
            result["top_growth_companies"] = df_to_records(tg)
        return result
    except Exception as e:
        return {"error": str(e), "industry": industry}


# ── Screener ─────────────────────────────────────────────────────────────────


@mcp.tool()
def screen_stocks(
    query: str = "most_actives",
    count: int = 25,
) -> dict:
    """Screen stocks using predefined Yahoo Finance screeners.

    Args:
        query: Predefined screener name. Options: "most_actives", "day_gainers",
               "day_losers", "most_shorted_stocks", "undervalued_growth_stocks",
               "undervalued_large_caps", "growth_technology_stocks",
               "aggressive_small_caps", "small_cap_gainers",
               "top_mutual_funds", "portfolio_anchors", "high_yield_bond".
        count: Number of results (default 25, max 250).

    Returns:
        dict with screener title, description, total matches, and stock quotes.
    """
    try:
        result = yf.screen(query, count=count)
        quotes = []
        for q in (result.get("quotes") or []):
            quotes.append({
                "symbol": q.get("symbol", ""),
                "shortName": q.get("shortName", ""),
                "regularMarketPrice": safe_value(q.get("regularMarketPrice")),
                "regularMarketChange": safe_value(q.get("regularMarketChange")),
                "regularMarketChangePercent": safe_value(q.get("regularMarketChangePercent")),
                "regularMarketVolume": safe_value(q.get("regularMarketVolume")),
                "marketCap": safe_value(q.get("marketCap")),
                "trailingPE": safe_value(q.get("trailingPE")),
                "exchange": q.get("exchange", ""),
            })
        return {
            "query": query,
            "title": result.get("title", ""),
            "description": result.get("description", ""),
            "total": result.get("total", 0),
            "count": len(quotes),
            "quotes": quotes,
        }
    except Exception as e:
        return {"error": str(e), "query": query}


# ── Batch Download ───────────────────────────────────────────────────────────


@mcp.tool()
def batch_download(
    tickers: list[str],
    period: str = "1mo",
    interval: str = "1d",
) -> dict:
    """Download OHLCV price history for multiple tickers at once.

    Args:
        tickers: List of ticker symbols (e.g. ["AAPL", "MSFT", "GOOGL"]).
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max).
        interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo).

    Returns:
        dict with per-ticker OHLCV records.
    """
    try:
        df = yf.download(tickers, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return {"tickers": tickers, "data": {}}
        result = {"tickers": tickers, "data": {}}
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    ticker_df = df.copy()
                else:
                    ticker_df = df.xs(ticker, level="Ticker", axis=1)
                result["data"][ticker] = df_to_records(ticker_df)
            except Exception:
                result["data"][ticker] = []
        return result
    except Exception as e:
        return {"error": str(e), "tickers": tickers}


def main():
    """Entry point for the yfinance-mcp command."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
