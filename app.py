import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Custom Strategy Backtester", layout="wide")
st.title("Chartink/Custom Strategy Backtester")

# Sidebar inputs
st.sidebar.header("Strategy Settings")
ticker = st.sidebar.text_input("Enter Ticker Symbol (e.g., RELIANCE.NS, INFY.NS, AAPL):", "RELIANCE.NS")
start_date = st.sidebar.date_input("Start Date", pd.to_datetime("2020-01-01"))
end_date = st.sidebar.date_input("End Date", pd.to_datetime("today"))
buy_amount = st.sidebar.number_input("Buy Amount (Rs)", value=10000)

if st.sidebar.button("Run Backtest"):
    with st.spinner("Fetching data and calculating conditions..."):
        # Fetch Data
        df = yf.download(ticker, start=start_date, end=end_date)
        
        if df.empty:
            st.error("No data found. Check the ticker symbol and date range.")
        else:
            # Flatten MultiIndex columns if present (common in newer yfinance versions)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # --- 1. Base Calculations ---
            df['min_250'] = df['Close'].rolling(window=250).min()
            df['max_250'] = df['Close'].rolling(window=250).max()
            
            # --- 2. Filter Condition ---
            # Daily count(250, 1 where daily close <= daily min(250, daily close)) = 0
            df['is_250_low'] = df['Close'] <= df['min_250']
            df['count_low_250'] = df['is_250_low'].rolling(window=250).sum()
            df['cond_filter'] = df['count_low_250'] == 0
            
            # --- 3. Buy Condition ---
            # (max(250, close) / close) >= max(250, max(250, close) / close)
            df['ratio_drop'] = df['max_250'] / df['Close']
            df['max_ratio_drop_250'] = df['ratio_drop'].rolling(window=250).max()
            df['is_max_drop'] = df['ratio_drop'] >= df['max_ratio_drop_250']
            
            # 1 day ago count(20) = 0
            df['count_max_drop_20_ago'] = df['is_max_drop'].shift(1).rolling(window=20).sum()
            
            # Final Buy Signal
            df['buy_signal'] = df['cond_filter'] & df['is_max_drop'] & (df['count_max_drop_20_ago'] == 0)
            
            # --- 4. Exit Condition ---
            # (close / min(250, close)) >= max(250, close / min(250, close))
            df['ratio_gain'] = df['Close'] / df['min_250']
            df['max_ratio_gain_250'] = df['ratio_gain'].rolling(window=250).max()
            df['is_max_gain'] = df['ratio_gain'] >= df['max_ratio_gain_250']
            
            # 1 day ago count(20) = 0
            df['count_max_gain_20_ago'] = df['is_max_gain'].shift(1).rolling(window=20).sum()
            
            # Final Sell Signal
            df['sell_signal'] = df['is_max_gain'] & (df['count_max_gain_20_ago'] == 0)
            
           # --- 5. Backtest Engine (With Dip Buying / Averaging Down) ---
quantity = 0.0
cash_deployed = 0.0
total_realized = 0.0
trades = []

last_buy_price = 0.0
dip_percentage_to_buy_again = 0.99  # 5% aur girne par firse buy karega (Aap isko 0.10 bhi kar sakte hain)

for date, row in df.iterrows():
    if pd.isna(row['Close']):
        continue
        
    price = float(row['Close'])
    
    # 1. Primary Buy (Jab aapki main condition true ho)
    if row['buy_signal']:
        qty_bought = buy_amount / price
        quantity += qty_bought
        cash_deployed += buy_amount
        last_buy_price = price  # Price save kar liya agle dip ke liye
        trades.append({
            "Date": date, "Type": "BUY (Primary)", "Price": round(price, 2), 
            "Quantity": round(qty_bought, 4), "Value": buy_amount, "Holdings": round(quantity, 4)
        })
    
    # 2. Secondary Buy (Agar pehle se hold hai, aur price aur 5% gir gaya)
    elif quantity > 0 and price <= last_buy_price * (1 - dip_percentage_to_buy_again):
        qty_bought = buy_amount / price
        quantity += qty_bought
        cash_deployed += buy_amount
        last_buy_price = price  # Naya lowest price save kar liya
        trades.append({
            "Date": date, "Type": "BUY (Averaging Dip)", "Price": round(price, 2), 
            "Quantity": round(qty_bought, 4), "Value": buy_amount, "Holdings": round(quantity, 4)
        })
    
    # 3. Execute Sell (Half Quantity on Strong Bounce)
    elif row['sell_signal'] and quantity > 0:
        qty_sold = quantity * 0.5
        sell_value = qty_sold * price
        quantity -= qty_sold
        total_realized += sell_value
        # Profit book karne ke baad last_buy_price reset kar sakte hain, ya waise hi chhod sakte hain
        trades.append({
            "Date": date, "Type": "SELL (Half Qty)", "Price": round(price, 2), 
            "Quantity": round(qty_sold, 4), "Value": round(sell_value, 2), "Holdings": round(quantity, 4)
        })
                
                # Execute Sell (Half Quantity)
                elif row['sell_signal'] and quantity > 0:
                    qty_sold = quantity * 0.5
                    sell_value = qty_sold * price
                    quantity -= qty_sold
                    total_realized += sell_value
                    trades.append({
                        "Date": date, "Type": "SELL", "Price": round(price, 2), 
                        "Quantity": round(qty_sold, 4), "Value": round(sell_value, 2), "Holdings": round(quantity, 4)
                    })
            
            # --- 6. Results Display ---
            col1, col2, col3 = st.columns(3)
            current_price = float(df['Close'].iloc[-1])
            unrealized_value = quantity * current_price
            total_portfolio_value = total_realized + unrealized_value
            
            col1.metric("Total Cash Deployed", f"₹{cash_deployed:,.2f}")
            col2.metric("Current Portfolio Value (Realized + Holdings)", f"₹{total_portfolio_value:,.2f}")
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
            
            # Candlestick chart
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
            
            # Buy markers
            buys = df[df['buy_signal']]
            fig.add_trace(go.Scatter(x=buys.index, y=buys['Close'], mode='markers', 
                                     marker=dict(color='green', size=12, symbol='triangle-up'), name='Buy Signal'))
            
            # Sell markers
            sells = df[df['sell_signal']]
            fig.add_trace(go.Scatter(x=sells.index, y=sells['Close'], mode='markers', 
                                     marker=dict(color='red', size=12, symbol='triangle-down'), name='Sell Signal'))
            
            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
