import base64
import datetime
import json
import uuid
import time
from typing import Any, Dict, Optional
import requests
from nacl.signing import SigningKey
import os
import colorama
from colorama import Fore, Style
import traceback
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization


# Initialize colorama
colorama.init(autoreset=True)
crypto_symbols = input('Enter the symbol for each crypto you want the bot to trade, separated only by a space: ').split(' ')
#API STUFF
try:
    with open('r_key.txt', 'r') as f:
        API_KEY = f.read()
    with open('r_secret.txt','r') as f:
        BASE64_PRIVATE_KEY = f.read()
except:
    # Generate the private key
    private_key = ed25519.Ed25519PrivateKey.generate()
    # Derive the public key from the private key
    public_key = private_key.public_key()

    # Serialize the public key (you may need to adjust the format per Robinhood's requirements)
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH
    )
    print("Your Public Key (Give this to Robinhood to create your API Key):\n", public_bytes.decode())

    # Serialize the private key in raw format (which gives exactly 32 bytes for Ed25519)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    API_KEY = input("API Key: ")
    # Base64-encode the raw bytes to store as text
    BASE64_PRIVATE_KEY = base64.b64encode(private_bytes).decode()
    with open('r_key.txt', 'w+') as f:
        f.write(API_KEY)
    with open('r_secret.txt','w+') as f:
        f.write(BASE64_PRIVATE_KEY)    
class CryptoAPITrading:
    def __init__(self):
        self.api_key = API_KEY
        private_key_seed = base64.b64decode(BASE64_PRIVATE_KEY)
        self.private_key = SigningKey(private_key_seed)
        self.base_url = "https://trading.robinhood.com"
        self.dca_levels_triggered = {}  # Track DCA levels for each crypto
        self.dca_levels = [-10.0, -20.0, -30.0, -40.0, -50.0]  # Moved to instance variable
        self.cost_basis = self.calculate_cost_basis()  # Initialize cost basis at startup
        self.initialize_dca_levels()  # Initialize DCA levels based on historical buy orders

    @staticmethod
    def _get_current_timestamp() -> int:
        return int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())

    def initialize_dca_levels(self):
        """
        Initializes the DCA levels_triggered dictionary based on the number of buy orders
        that have occurred after the first buy order following the most recent sell order
        for each cryptocurrency.
        """
        holdings = self.get_holdings()
        if not holdings or "results" not in holdings:
            print("No holdings found. Skipping DCA levels initialization.")
            return

        for holding in holdings.get("results", []):
            symbol = holding["asset_code"]

            full_symbol = f"{symbol}-USD"
            orders = self.get_orders(full_symbol)
            
            if not orders or "results" not in orders:
                print(f"No orders found for {full_symbol}. Skipping.")
                continue

            # Filter for filled buy and sell orders
            filled_orders = [
                order for order in orders["results"]
                if order["state"] == "filled" and order["side"] in ["buy", "sell"]
            ]
            
            if not filled_orders:
                print(f"No filled buy or sell orders for {full_symbol}. Skipping.")
                continue

            # Sort orders by creation time in ascending order (oldest first)
            filled_orders.sort(key=lambda x: x["created_at"])

            # Find the timestamp of the most recent sell order
            most_recent_sell_time = None
            for order in reversed(filled_orders):
                if order["side"] == "sell":
                    most_recent_sell_time = order["created_at"]
                    break

            # Determine the cutoff time for buy orders
            if most_recent_sell_time:
                # Find all buy orders after the most recent sell
                relevant_buy_orders = [
                    order for order in filled_orders
                    if order["side"] == "buy" and order["created_at"] > most_recent_sell_time
                ]
                if not relevant_buy_orders:
                    print(f"No buy orders after the most recent sell for {full_symbol}.")
                    self.dca_levels_triggered[symbol] = []
                    continue
                print(f"Most recent sell for {full_symbol} at {most_recent_sell_time}.")
            else:
                # If no sell orders, consider all buy orders
                relevant_buy_orders = [
                    order for order in filled_orders
                    if order["side"] == "buy"
                ]
                if not relevant_buy_orders:
                    print(f"No buy orders for {full_symbol}. Skipping.")
                    self.dca_levels_triggered[symbol] = []
                    continue
                print(f"No sell orders found for {full_symbol}. Considering all buy orders.")

            # Ensure buy orders are sorted by creation time ascending
            relevant_buy_orders.sort(key=lambda x: x["created_at"])

            # Identify the first buy order in the relevant list
            first_buy_order = relevant_buy_orders[0]
            first_buy_time = first_buy_order["created_at"]

            # Count the number of buy orders after the first buy
            buy_orders_after_first = [
                order for order in relevant_buy_orders
                if order["created_at"] > first_buy_time
            ]

            triggered_levels_count = len(buy_orders_after_first)
            
            # Assign the corresponding DCA levels that have been triggered
            # For example, if 2 buy orders after the first, trigger the first 2 DCA levels
            triggered_levels = self.dca_levels[:triggered_levels_count]
            
            self.dca_levels_triggered[symbol] = triggered_levels
            print(f"Initialized DCA levels for {symbol}: {triggered_levels}")

    def make_api_request(self, method: str, path: str, body: Optional[str] = "") -> Any:
        timestamp = self._get_current_timestamp()
        headers = self.get_authorization_header(method, path, body, timestamp)
        url = self.base_url + path

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=json.loads(body), timeout=10)

            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            try:
                # Parse and return the JSON error response
                error_response = response.json()
                return error_response  # Return the JSON error for further handling
            except Exception:
                return None
        except Exception:
            return None

    def get_authorization_header(
            self, method: str, path: str, body: str, timestamp: int
    ) -> Dict[str, str]:
        message_to_sign = f"{self.api_key}{timestamp}{path}{method}{body}"
        signed = self.private_key.sign(message_to_sign.encode("utf-8"))

        return {
            "x-api-key": self.api_key,
            "x-signature": base64.b64encode(signed.signature).decode("utf-8"),
            "x-timestamp": str(timestamp),
        }

    def get_account(self) -> Any:
        path = "/api/v1/crypto/trading/accounts/"
        return self.make_api_request("GET", path)

    def get_holdings(self) -> Any:
        path = "/api/v1/crypto/trading/holdings/"
        return self.make_api_request("GET", path)

    def get_trading_pairs(self) -> Any:
        path = "/api/v1/crypto/trading/trading_pairs/"
        response = self.make_api_request("GET", path)

        if not response or "results" not in response:
            return []

        trading_pairs = response.get("results", [])
        if not trading_pairs:
            return []

        return trading_pairs

    def get_orders(self, symbol: str) -> Any:
        path = f"/api/v1/crypto/trading/orders/?symbol={symbol}"
        return self.make_api_request("GET", path)

    def calculate_cost_basis(self):
        holdings = self.get_holdings()
        if not holdings or "results" not in holdings:
            return {}

        active_assets = {holding["asset_code"] for holding in holdings.get("results", [])}
        current_quantities = {
            holding["asset_code"]: float(holding["total_quantity"])
            for holding in holdings.get("results", [])
        }

        cost_basis = {}

        for asset_code in active_assets:
            orders = self.get_orders(f"{asset_code}-USD")
            if not orders or "results" not in orders:
                continue

            # Get all filled buy orders, sorted from most recent to oldest
            buy_orders = [
                order for order in orders["results"]
                if order["side"] == "buy" and order["state"] == "filled"
            ]
            buy_orders.sort(key=lambda x: x["created_at"], reverse=True)

            remaining_quantity = current_quantities[asset_code]
            total_cost = 0.0

            for order in buy_orders:
                for execution in order.get("executions", []):
                    quantity = float(execution["quantity"])
                    price = float(execution["effective_price"])

                    if remaining_quantity <= 0:
                        break

                    # Use only the portion of the quantity needed to match the current holdings
                    if quantity > remaining_quantity:
                        total_cost += remaining_quantity * price
                        remaining_quantity = 0
                    else:
                        total_cost += quantity * price
                        remaining_quantity -= quantity

                if remaining_quantity <= 0:
                    break

            if current_quantities[asset_code] > 0:
                cost_basis[asset_code] = total_cost / current_quantities[asset_code]
            else:
                cost_basis[asset_code] = 0.0

        return cost_basis

    def get_price(self, symbols: list) -> Dict[str, float]:
        buy_prices = {}
        sell_prices = {}
        valid_symbols = []

        for symbol in symbols:
            if symbol == "USDC-USD":
                continue
            path = f"/api/v1/crypto/marketdata/best_bid_ask/?symbol={symbol}"
            response = self.make_api_request("GET", path)

            if response and "results" in response:
                result = response["results"][0]
                buy_prices[symbol] = float(result["ask_inclusive_of_buy_spread"])
                sell_prices[symbol] = float(result["bid_inclusive_of_sell_spread"])
                valid_symbols.append(symbol)
            else:
                pass

        return buy_prices, sell_prices, valid_symbols

    def place_buy_order(self, client_order_id: str, side: str, order_type: str, symbol: str, amount_in_usd: float) -> Any:
        # Fetch the current price of the asset
        current_buy_prices, current_sell_prices, valid_symbols = self.get_price([symbol])
        current_price = current_buy_prices[symbol]
        asset_quantity = amount_in_usd / current_price

        max_retries = 5
        retries = 0

        while retries < max_retries:
            retries += 1
            try:
                # Default precision to 8 decimals initially
                rounded_quantity = round(asset_quantity, 8)

                body = {
                    "client_order_id": client_order_id,
                    "side": side,
                    "type": order_type,
                    "symbol": symbol,
                    "market_order_config": {
                        "asset_quantity": f"{rounded_quantity:.8f}"  # Start with 8 decimal places
                    }
                }

                path = "/api/v1/crypto/trading/orders/"
                response = self.make_api_request("POST", path, json.dumps(body))
                if "errors" not in response:
                    return response  # Successfully placed order
            except Exception as e:
                pass #print(traceback.format_exc())
                

            # Check for precision errors
            if response and "errors" in response:
                for error in response["errors"]:
                    if "has too much precision" in error.get("detail", ""):
                        # Extract required precision directly from the error message
                        detail = error["detail"]
                        nearest_value = detail.split("nearest ")[1].split(" ")[0]
                        decimal_places = len(nearest_value.split(".")[1].rstrip("0"))
                        asset_quantity = round(asset_quantity, decimal_places)
                        break
                    elif "must be greater than or equal to" in error.get("detail", ""):
                        return None

        return None

    def place_sell_order(self, client_order_id: str, side: str, order_type: str, symbol: str, asset_quantity: float) -> Any:
        body = {
            "client_order_id": client_order_id,
            "side": side,
            "type": order_type,
            "symbol": symbol,
            "market_order_config": {
                "asset_quantity": f"{asset_quantity:.8f}"
            }
        }

        path = "/api/v1/crypto/trading/orders/"
        return self.make_api_request("POST", path, json.dumps(body))

    def manage_trades(self):
        trades_made = False  # Flag to track if any trade was made in this iteration
        # Fetch account details
        account = self.get_account()
        # Fetch holdings
        holdings = self.get_holdings()
        # Fetch trading pairs
        trading_pairs = self.get_trading_pairs()
        # Use the stored cost_basis instead of recalculating
        cost_basis = self.cost_basis
        # Fetch current prices
        symbols = [holding["asset_code"] + "-USD" for holding in holdings.get("results", [])]

        current_buy_prices, current_sell_prices, valid_symbols = self.get_price(symbols)
        # Calculate total account value
        buying_power = float(account.get("buying_power", 0))
        holdings_buy_value = sum(
            float(holding["total_quantity"]) * current_buy_prices.get(f"{holding['asset_code']}-USD", 0)
            for holding in holdings.get("results", [])
            if f"{holding['asset_code']}-USD" in valid_symbols and holding["asset_code"] != "USDC"
        )
        holdings_sell_value = sum(
            float(holding["total_quantity"]) * current_sell_prices.get(f"{holding['asset_code']}-USD", 0)
            for holding in holdings.get("results", [])
            if f"{holding['asset_code']}-USD" in valid_symbols and holding["asset_code"] != "USDC"
        )
        total_account_value = buying_power + holdings_sell_value
        in_use = (holdings_sell_value / total_account_value) * 100 if total_account_value > 0 else 0
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n--- Account Summary ---")
        print(f"Total Account Value: ${total_account_value:.2f}")
        print(f"Holdings Value: ${holdings_sell_value:.2f}")
        print(f"Percent In Trade: {in_use:.2f}%")
        print("\n--- Current Trades ---")
        for holding in holdings.get("results", []):
            symbol = holding["asset_code"]
            full_symbol = f"{symbol}-USD"

            if full_symbol not in valid_symbols or symbol == "USDC":
                continue

            quantity = float(holding["total_quantity"])
            current_buy_price = current_buy_prices.get(full_symbol, 0)
            current_sell_price = current_sell_prices.get(full_symbol, 0)
            avg_cost_basis = cost_basis.get(symbol, 0)

            if avg_cost_basis > 0:
                gain_loss_percentage_buy = ((current_buy_price - avg_cost_basis) / avg_cost_basis) * 100
                gain_loss_percentage_sell = ((current_sell_price - avg_cost_basis) / avg_cost_basis) * 100
            else:
                gain_loss_percentage_buy = 0
                gain_loss_percentage_sell = 0
                print(f"  Warning: Average Cost Basis is 0 for {symbol}, Gain/Loss calculation skipped.")

            value = quantity * current_sell_price
            triggered_levels_count = len(self.dca_levels_triggered.get(symbol, []))
            triggered_levels = triggered_levels_count  # Number of DCA levels triggered

            # Determine the next DCA level
            if triggered_levels_count < len(self.dca_levels):
                next_dca_level = self.dca_levels[triggered_levels_count]
                next_dca_display = f"{next_dca_level:.4f}%"
            else:
                next_dca_display = "N/A"

            # Set color code: green for positive, red for negative gain/loss
            if gain_loss_percentage_buy >= 0:
                color = Fore.GREEN
            else:
                color = Fore.RED
            if gain_loss_percentage_sell >= 0:
                color2 = Fore.GREEN
            else:
                color2 = Fore.RED
            
            # Updated print statement to include Next DCA Level
            print(f"\nSymbol: {symbol}  |  Gain/Loss DCA: {color}{gain_loss_percentage_buy:.2f}%{Style.RESET_ALL} (Next DCA: {next_dca_level:.2f}) |  Gain/Loss SELL: {color2}{gain_loss_percentage_sell:.2f}%{Style.RESET_ALL}  |  DCA Levels Triggered: {triggered_levels}  |  Trade Value: ${value:.2f}")

            # Sell at predefined gain thresholds
            if gain_loss_percentage_sell >= 5.0:
                print(f"  Selling {symbol} at 5% gain.")
                response = self.place_sell_order(
                    str(uuid.uuid4()), "sell", "market", full_symbol, quantity
                )

                trades_made = True
                print(f"  Successfully sold {quantity} {symbol}.")
                time.sleep(5)
                holdings = self.get_holdings()
            else:
                pass
            # DCA at loss thresholds
            if gain_loss_percentage_buy <= self.dca_levels[0]:  # Start checking from the first DCA level
                for level in self.dca_levels:
                    if gain_loss_percentage_buy <= level and (
                        symbol not in self.dca_levels_triggered
                        or level not in self.dca_levels_triggered[symbol]
                    ):
                        print(f"  DCAing {symbol} at {level:.4f}% loss.")

                        print(f"  Current Value: ${value:.2f}")
                        dca_amount = value * 2
                        print(f"  DCA Amount: ${dca_amount:.2f}")
                        print(f"  Buying Power: ${buying_power:.2f}")
                        if dca_amount <= buying_power:
                            response = self.place_buy_order(
                                str(uuid.uuid4()),
                                "buy",
                                "market",
                                full_symbol,
                                dca_amount,
                            )
                            print(f"  Buy Response: {response}")
                            if response and "errors" not in response:
                                self.dca_levels_triggered.setdefault(symbol, []).append(level)
                                trades_made = True
                                print(f"  Successfully placed DCA buy order for {symbol}.")
                            else:
                                print(f"  Failed to place DCA buy order for {symbol}.")
                        else:
                            print(f"  Skipping DCA for {symbol}. Not enough funds.")
                        break
            else:
                pass

        if not trading_pairs:
            return
        if in_use < 50:
            # Start new trades
            trade_alloc_per_new = total_account_value * 0.001
            
            if trade_alloc_per_new < 0.5:
                trade_alloc_per_new = 0.5
            
            start_index = 0
            while True:
                
                # Check if already being held
                if crypto_symbols[start_index] + '-USD' not in [f"{holding['asset_code']}-USD" for holding in holdings.get("results", [])]:
                    allocation_in_usd = trade_alloc_per_new
                    #print(crypto_symbols[start_index])
                    #print('not in holdings')
                    response = self.place_buy_order(
                        str(uuid.uuid4()),
                        "buy",
                        "market",
                        crypto_symbols[start_index] + '-USD',
                        allocation_in_usd,
                    )
                    #print(response)
                    if response and "errors" not in response:
                        trades_made = True
                        self.dca_levels_triggered[symbol] = []
                        print(f"Starting new trade for {crypto_symbols[start_index]}-USD. Allocating ${allocation_in_usd:.2f}.")
                start_index += 1
                if start_index >= len(crypto_symbols):
                    break
                else:
                    continue
        else:
            pass
        # If any trades were made, recalculate the cost basis
        if trades_made:
            time.sleep(5)
            print("Trades were made in this iteration. Recalculating cost basis...")
            new_cost_basis = self.calculate_cost_basis()
            if new_cost_basis:
                self.cost_basis = new_cost_basis
                print("Cost basis recalculated successfully.")
            else:
                print("Failed to recalculcate cost basis.")
            self.initialize_dca_levels()

    def run(self):
        while True:
            try:
                self.manage_trades()
                time.sleep(0.5)
            except Exception as e:
                print(traceback.format_exc())

if __name__ == "__main__":
    trading_bot = CryptoAPITrading()
    trading_bot.run()
