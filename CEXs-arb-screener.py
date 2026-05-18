import ccxt
import concurrent.futures
from typing import Dict, List, Optional, Any

# Configuration
EXCHANGE_IDS: List[str] = [
    'binance', 'bybit', 'kucoin', 'bitget', 'bitmart', 
    'coinex', 'bingx', 'bitrue', 'xt', 'mexc', 'ascendex'
]
QUOTE_CURRENCY: str = 'USDT'
MIN_SPREAD_PERCENT: float = 0.5  # Minimum % profit to report

# Updated Volume Constraints per your request
MIN_VOLUME_USDT: float = 10000.0
MAX_VOLUME_USDT: float = 60000.0

# Blacklist for specific tokens
BLACKLISTED_TOKENS: List[str] = ['ZKP'] 

class ArbitrageScanner:
    def __init__(self, exchange_ids: List[str]):
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        for eid in exchange_ids:
            try:
                exchange_class = getattr(ccxt, eid)
                self.exchanges[eid] = exchange_class({'enableRateLimit': True})
            except AttributeError:
                print(f"Exchange {eid} not supported by CCXT.")

    def fetch_data(self, exchange_id: str) -> Dict[str, Any]:
        """Fetch markets, currencies, and tickers for a specific exchange."""
        ex = self.exchanges[exchange_id]
        try:
            ex.load_markets()
            tickers = ex.fetch_tickers()
            usdt_tickers = {s: t for s, t in tickers.items() if s.endswith(f'/{QUOTE_CURRENCY}')}
            return {
                'id': exchange_id,
                'tickers': usdt_tickers,
                'currencies': ex.currencies,
                'exchange': ex
            }
        except Exception as e:
            return {'id': exchange_id, 'error': str(e)}

    def _get_contract(self, network_info: Dict) -> str:
        """Helper to extract contract address from inconsistent exchange metadata."""
        addr = network_info.get('address') or network_info.get('contract') or \
               network_info.get('info', {}).get('contractAddress') or \
               network_info.get('info', {}).get('tokenAddress') or ""
        return str(addr).strip().lower()

    def get_shared_network(self, coin: str, buy_ex_data: Dict, sell_ex_data: Dict) -> Optional[Dict]:
        """Verify shared network AND identical contract addresses."""
        c_buy = buy_ex_data['currencies'].get(coin)
        c_sell = sell_ex_data['currencies'].get(coin)

        if not c_buy or not c_sell:
            return None

        if not (c_buy.get('active', True) and c_sell.get('active', True)):
            return None

        networks_buy = c_buy.get('networks', {})
        networks_sell = c_sell.get('networks', {})

        for net_id, info_buy in networks_buy.items():
            if net_id in networks_sell:
                info_sell = networks_sell[net_id]
                
                if info_buy.get('withdraw') and info_sell.get('deposit'):
                    addr_buy = self._get_contract(info_buy)
                    addr_sell = self._get_contract(info_sell)

                    if addr_buy == addr_sell:
                        return {
                            'net_id': net_id,
                            'contract': addr_buy if addr_buy else "Native Asset"
                        }
        return None

    def scan(self):
        print(f"Scanning {len(self.exchanges)} exchanges for arbitrage...")
        print(f"Volume Filter: {MIN_VOLUME_USDT} - {MAX_VOLUME_USDT} {QUOTE_CURRENCY}")
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = list(executor.map(self.fetch_data, self.exchanges.keys()))

        valid_data = [r for r in results if 'error' not in r]
        opportunities_found = False

        for i in range(len(valid_data)):
            for j in range(i + 1, len(valid_data)):
                ex1, ex2 = valid_data[i], valid_data[j]
                common_symbols = set(ex1['tickers'].keys()) & set(ex2['tickers'].keys())

                for symbol in common_symbols:
                    coin = symbol.split('/')[0]

                    if coin.upper() in BLACKLISTED_TOKENS:
                        continue

                    t1, t2 = ex1['tickers'][symbol], ex2['tickers'][symbol]
                    
                    if not all([t1.get('ask'), t2.get('bid'), t1.get('bid'), t2.get('ask')]):
                        continue

                    scenarios = [
                        (ex1, ex2, t1, t2, f"Buy @ {ex1['id']} / Sell @ {ex2['id']}"),
                        (ex2, ex1, t2, t1, f"Buy @ {ex2['id']} / Sell @ {ex1['id']}")
                    ]

                    for buy_ex_data, sell_ex_data, buy_tick, sell_tick, label in scenarios:
                        buy_p = buy_tick['ask']
                        sell_p = sell_tick['bid']
                        
                        if buy_p <= 0: continue
                        
                        # --- VOLUME FILTER LOGIC ---
                        v_buy = buy_tick.get('quoteVolume') or (buy_tick.get('baseVolume', 0) * buy_p)
                        v_sell = sell_tick.get('quoteVolume') or (sell_tick.get('baseVolume', 0) * sell_p)

                        # Filter: must be between 10k and 60k on BOTH exchanges
                        if not (MIN_VOLUME_USDT <= v_buy <= MAX_VOLUME_USDT and 
                                MIN_VOLUME_USDT <= v_sell <= MAX_VOLUME_USDT):
                            continue
                        # ---------------------------

                        spread = ((sell_p - buy_p) / buy_p) * 100

                        if spread >= MIN_SPREAD_PERCENT:
                            match = self.get_shared_network(coin, buy_ex_data, sell_ex_data)
                            if match:
                                print("-" * 45)
                                print(f"Token: {coin} | Profit: {spread:.2f}%")
                                print(f"Volumes: Buy Ex: {v_buy:.0f} | Sell Ex: {v_sell:.0f} USDT")
                                print(f"Network: {match['net_id']} | Contract: {match['contract']}")
                                print(f"Action: {label} ({buy_p} -> {sell_p})")
                                opportunities_found = True

        if not opportunities_found:
            print("No Arbitrage Found matching volume and contract criteria.")

if __name__ == "__main__":
    scanner = ArbitrageScanner(EXCHANGE_IDS)
    scanner.scan()