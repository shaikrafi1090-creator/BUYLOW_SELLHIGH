import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import os

st.set_page_config(page_title="Custom Strategy Backtester", layout="wide")
st.title("Chartink/Custom Strategy Backtester")

@st.cache_data
def load_symbols():
    # Referencing the exact file uploaded to the repository
    file_path = "STOCK SYMBOLS (5).csv"
    if os.path.exists(file_path):
        df_symbols = pd.read_csv(file_path)
        if 'Symbol' in df_symbols.columns:
            return df_symbols['Symbol'].astype(str).tolist()
        else:
            return df_symbols.iloc[:, 0].astype(str).tolist()
    return ["RELIANCE", "TCS", "INFY", "HDFCBANK"]

symbols_list = load_symbols()

# --- Sidebar inputs ---
st.sidebar.header("Strategy Settings")
selected_symbol = st.sidebar.selectbox("Select Ticker from CSV:", symbols_list)

add_ns = st.sidebar.checkbox("Append '.NS' to symbol for Yahoo Finance", value=True)
ticker = f"{selected_symbol}.NS" if add_ns and not selected_symbol.endswith('.NS') else selected_symbol

start_date = st.sidebar.date_input("Start Date", pd.to_datetime("2020-01-01"))
end_date = st.sidebar.date_input("End Date", pd.to_datetime("today"))
buy_amount = st.sidebar.number_input("Buy Amount (Rs)", value=10000)

# Naya Slider Averaging Down ke liye
dip_percentage_input = st.sidebar.slider(
    "Averaging Dip Percentage (%)", 
    min_value=1.0, 
    max_value=20.0, 
    value=5.0, 
    step=0.5,
    help="Agar stock itne % aur girta hai toh ye firse Rs 10000 ka buy karega."
)
dip_percentage_to_buy_again = dip_percentage_input / 100.0

if st.sidebar.button("Run Backtest"):
    with st.spinner(f"Fetching data for {ticker} and calculating conditions..."):
        df = yf.download(ticker, start=start_date, end=end_date)
        
        if df.empty:
            st.error(f"No data found for {ticker}. Try unchecking the '.NS' box if it's a US stock, or verify the date range.")
        else:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # --- 1. Base Calculations ---
            df['min_250'] = df['Close'].rolling(window=250).min()
            df['max_250'] = df['Close'].rolling(window=250).max()
            
            # --- 2. Filter Condition ---
            df['is_250_low'] = df['Close'] <= df['min_250']
            df['count_low_250'] = df['is_250_low'].rolling(window=250).sum()
            df['cond_filter'] = df['count_low_250'] == 0
            
            # --- 3. Primary Buy Condition ---
            df['ratio_drop'] = df['max_250'] / df['Close']
            df['max_ratio_drop_250'] = df['ratio_drop'].rolling(window=250).max()
            df['is_max_drop'] = df['ratio_drop'] >= df['max_ratio_drop_250']
            
            df['count_max_drop_20_ago'] = df['is_max_drop'].shift(1).rolling(window=20).sum()
            df['buy_signal'] = df['cond_filter'] & df['is_max_drop'] & (df['count_max_drop_20_ago'] == 0)
            
            # --- 4. Exit Condition ---
            df['ratio_gain'] = df['Close'] / df['min_250']
            df['max_ratio_gain_250'] = df['ratio_gain'].rolling(window=250).max()
            df['is_max_gain'] = df['ratio_gain'] >= df['max_ratio_gain_250']
            
            df['count_max_gain_20_ago'] = df['is_max_gain'].shift(1).rolling(window=20).sum()
            df['sell_signal'] = df['is_max_gain'] & (df['count_max_gain_20_ago'] == 0)
            
            # --- 5. Backtest Engine ---
            quantity = 0.0
            cash_deployed = 0.0
            total_realized = 0.0
            trades = []
            
            last_buy_price = 0.0
            
            for date, row in df.iterrows():
                if pd.isna(row['Close']):
                    continue
                    
                price = float(row['Close'])
                
                # Condition A: Primary Buy
                if row['buy_signal']:
                    qty_bought = buy_amount / price
                    quantity += qty_bought
                    cash_deployed += buy_amount
                    last_buy_price = price
                    trades.append({
                        "Date": date, "Type": "BUY (Primary)", "Price": round(price, 2), 
                        "Quantity": round(qty_bought, 4), "Value": buy_amount, "Holdings": round(quantity, 4)
                    })
                
                # Condition B: Secondary Buy (Averaging Dip)
                elif quantity > 0 and price <= last_buy_price * (1 - dip_percentage_to_buy_again):
                    qty_bought = buy_amount / price
                    quantity += qty_bought
                    cash_deployed += buy_amount
                    last_buy_price = price
                    trades.append({
                        "Date": date, "Type": "BUY (Averaging Dip)", "Price": round(price, 2), 
                        "Quantity": round(qty_bought, 4), "Value": buy_amount, "Holdings": round(quantity, 4)
                    })
                
                # Condition C: Sell Half Quantity
                elif row['sell_signal'] and quantity > 0:
                    qty_sold = quantity * 0.5
                    sell_value = qty_sold * price
                    quantity -= qty_sold
                    total_realized += sell_value
                    trades.append({
                        "Date": date, "Type": "SELL (Half Qty)", "Price": round(price, 2), 
                        "Quantity": round(qty_sold, 4), "Value": round(sell_value, 2), "Holdings": round(quantity, 4)
                    })
            
            # --- 6. Results Display ---
            col1, col2, col3 = st.columns(3)
            current_price = float(df['Close'].iloc[-1])
            unrealized_value = quantity * current_price
            total_portfolio_value = total_realized + unrealized_value
            
            col1.metric("Total Cash Deployed", f"₹{cash_deployed:,.2f}")
            col2.metric("Current Portfolio Value", f"₹{total_portfolio_value:,.2f}")
            col3.metric("Net P&L", f"₹{(total_portfolio_value - cash_deployed):,.2f}")
            
            st.subheader("Trade Log")
            if trades:
                trades_df = pd.DataFrame(trades).set_index("Date")
                st.dataframe(trades_df, use_container_width=True)
            else:
                st.write("No trades executed based on these conditions in the given timeframe.")
            
            # --- 7. Charting ---
            st.subheader("Price Chart with Buy/Sell Signals")
            fig = go.Figure()
            
            # Main Candlestick
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
            
            # Extract points from trades for accurate plotting
            if trades:
                primary_dates = [t['Date'] for t in trades if t['Type'] == "BUY (Primary)"]
                primary_prices = [t['Price'] for t in trades if t['Type'] == "BUY (Primary)"]
                
                avg_dates = [t['Date'] for t in trades if t['Type'] == "BUY (Averaging Dip)"]
                avg_prices = [t['Price'] for t in trades if t['Type'] == "BUY (Averaging Dip)"]
                
                sell_dates = [t['Date'] for t in trades if t['Type'] == "SELL (Half Qty)"]
                sell_prices = [t['Price'] for t in trades if t['Type'] == "SELL (Half Qty)"]
                
                fig.add_trace(go.Scatter(x=primary_dates, y=primary_prices, mode='markers', 
                                         marker=dict(color='lime', size=12, symbol='triangle-up'), name='Primary Buy'))
                
                fig.add_trace(go.Scatter(x=avg_dates, y=avg_prices, mode='markers', 
                                         marker=dict(color='cyan', size=10, symbol='triangle-up'), name='Average Dip Buy'))
                                         
                fig.add_trace(go.Scatter(x=sell_dates, y=sell_prices, mode='markers', 
                                         marker=dict(color='red', size=12, symbol='triangle-down'), name='Sell Half'))
            
            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
