from serverless_wsgi import handle_request
from flask import Flask, render_template, request, jsonify, send_from_directory
import pandas as pd
import numpy as np
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'  # Changed for Vercel compatibility
app.config['ALLOWED_EXTENSIONS'] = {'xlsx', 'xls'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def process_data(filepath):
    try:
        # Load and process the data
        df = pd.read_excel(filepath)
        
        # Ensure required columns exist
        required_columns = ['Date', 'Product', 'Total Orders']
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Convert and extract date components
        df['Date'] = pd.to_datetime(df['Date'])
        df['Year'] = df['Date'].dt.year
        df['Month'] = df['Date'].dt.month
        df['Day'] = df['Date'].dt.day
        
        # Filter for May date ranges by year
        may_data = df[df['Month'] == 5]
        filtered_data = pd.concat([
            may_data[(may_data['Year'] == 2022) & (may_data['Day'].between(23, 29))],
            may_data[(may_data['Year'] == 2023) & (may_data['Day'].between(22, 28))],
            may_data[(may_data['Year'] == 2024) & (may_data['Day'].between(20, 26))]
        ])
        
        # Pivot and calculate metrics
        result = (filtered_data.groupby(['Product', 'Year'])['Total Orders']
                  .sum()
                  .unstack()
                  .reset_index()
                  .fillna(0))
        
        # Calculate metrics
        result['avg'] = result[[2022, 2023, 2024]].mean(axis=1).round(2)
        result['min'] = result[[2022, 2023, 2024]].min(axis=1)
        
        def calculate_cov(row):
            years_data = row[[2022, 2023, 2024]]
            std_dev = np.std(years_data, ddof=0)
            mean = np.mean(years_data)
            return (std_dev / mean) * 100 if mean != 0 else 0
        
        result['cov'] = result.apply(calculate_cov, axis=1).round(2)
        
        # Revised Top7 calculation that includes all products with same order quantity as 7th product
        top7_counts = {}
        
        for year in [2022, 2023, 2024]:
            # Sort products by sales (descending) and then by name (ascending) for consistency
            yearly_sales = result[['Product', year]].sort_values(
                by=[year, 'Product'], 
                ascending=[False, True]
            )
            
            if len(yearly_sales) >= 7:
                # Get the sales value of the 7th product
                cutoff_value = yearly_sales.iloc[6][year]
                # Include all products with sales >= cutoff value
                top_products = yearly_sales[yearly_sales[year] >= cutoff_value]['Product']
            else:
                # If less than 7 products, include all
                top_products = yearly_sales['Product']
            
            for product in top_products:
                top7_counts[product] = top7_counts.get(product, 0) + 1
        
        result['top7'] = result['Product'].map(top7_counts).fillna(0).astype(int)
        
        # Normalization
        def normalize(col):
            col_min = col.min()
            col_max = col.max()
            return (col - col_min) / (col_max - col_min) if (col_max - col_min) != 0 else 0
        
        result['n-avg'] = normalize(result['avg'])
        result['n-min'] = normalize(result['min'])
        result['n-cov'] = (result['cov'].max() - result['cov']) / (result['cov'].max() - result['cov'].min())
        result['n-top7'] = result['top7'] / 3
        
        # Final score
        result['out of 10'] = ((result['n-avg'] * 0.4 + 
                               result['n-min'] * 0.2 + 
                               result['n-cov'] * 0.3 + 
                               result['n-top7'] * 0.1) * 10).round(3)
        
        # Rank with no ties - use the 'first' method which gives increasing ranks
        # First sort by score descending, then by product name for consistency
        result = result.sort_values(['out of 10', 'Product'], ascending=[False, True])
        result['rank'] = range(1, len(result)+1)
        
        return result[['Product', 'rank', 'out of 10', 'top7']].to_dict('records')
    
    except Exception as e:
        raise ValueError(f"Error processing data: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            processed_data = process_data(filepath)
            return jsonify({
                'success': True,
                'data': processed_data,
                'filename': filename
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'error': 'Allowed file types are xlsx, xls'}), 400

def vercel_handler(request, context):
    return handle_request(app, request, context)

if __name__ == '__main__':
    app.run(debug=True)
# Add this below all your existing code
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)