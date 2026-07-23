import pandas as pd
import numpy as np
import io
import re


class SmartDataAnalyzer:
    def __init__(self, file_bytes: bytes, filename: str):
        self.filename = filename
        self.df = self._load_file(file_bytes, filename)
        self.df = self._clean_data(self.df)

    def _load_file(self, file_bytes: bytes, filename: str) -> pd.DataFrame:
        if filename.endswith('.csv'):
            return pd.read_csv(io.BytesIO(file_bytes))
        elif filename.endswith(('.xlsx', '.xls')):
            return pd.read_excel(io.BytesIO(file_bytes))
        else:
            raise ValueError("Faqat CSV yoki Excel (.xlsx, .xls) fayllari qo'llab-quvvatlanadi.")

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(how='all')
        return df

    def _parse_money(self, val):
        if pd.isna(val): return 0.0
        val = str(val).strip()

        val = re.sub(r'[^\d\,\.\-]', '', val)
        if not val: return 0.0

        if ',' in val and '.' in val:
            if val.rfind(',') > val.rfind('.'):
                val = val.replace('.', '').replace(',', '.')
            else:
                val = val.replace(',', '')
        else:
            if ',' in val:
                parts = val.split(',')
                if len(parts) > 2 or len(parts[-1]) == 3:
                    val = val.replace(',', '')
                else:
                    val = val.replace(',', '.')
        try:
            return float(val)
        except:
            return 0.0

    def analyze(self) -> dict:
        cols = self.df.columns.tolist()

        # ==========================================
        # 🚀 BUG FIX 2: SOTUVCHI VA ISMLARNI CHETLAB O'TISH
        # ==========================================
        revenue_keywords = ['sum', 'price', 'tushum', 'amount', 'narx', 'total', 'sotuv', 'qiymat', 'pul']
        # Endi tizim "Sotuvchi", "Ism", "Xodim" kabi so'zlarni ham pul deb o'ylamaydi!
        exclude_keywords = ['id', 'nomer', 'raqam', '№', 'sana', 'date', 'sotuvchi', 'ism', 'xodim', 'menejer',
                            'manager', 'name', 'mijoz']

        revenue_col = next(
            (c for c in cols if any(k in c for k in revenue_keywords) and not any(ex in c for ex in exclude_keywords)),
            None)

        if revenue_col:
            self.df[revenue_col] = self.df[revenue_col].apply(self._parse_money)

        numeric_cols = self.df.select_dtypes(include=[np.number]).columns.tolist()
        text_cols = self.df.select_dtypes(include=['object', 'category']).columns.tolist()

        if not numeric_cols:
            raise ValueError("Faylda raqamli ma'lumotlar topilmadi!")

        if not revenue_col:
            valid_numeric = [c for c in numeric_cols if not any(ex in c for ex in exclude_keywords)]
            revenue_col = valid_numeric[0] if valid_numeric else numeric_cols[0]

        product_col = next(
            (c for c in text_cols if any(k in c for k in ['product', 'mahsulot', 'item', 'nomi', 'tovar'])),
            text_cols[0] if text_cols else "Mahsulot")
        seller_col = next((c for c in text_cols if
                           any(k in c for k in ['seller', 'sotuvchi', 'user', 'xodim', 'manager', 'menejer'])),
                          text_cols[1] if len(text_cols) > 1 else product_col)
        category_col = next((c for c in text_cols if any(k in c for k in ['category', 'kategoriya', 'tur', 'group'])),
                            text_cols[-1] if text_cols else "Kategoriya")

        self.df[revenue_col] = self.df[revenue_col].fillna(0)

        total_revenue = float(self.df[revenue_col].sum())
        total_tx = len(self.df)
        avg_check = float(self.df[revenue_col].mean()) if total_tx > 0 else 0.0

        pareto_data = []
        if product_col in self.df.columns:
            prod_grp = self.df.groupby(product_col)[revenue_col].sum().sort_values(ascending=False).reset_index()
            prod_grp['cum_pct'] = (prod_grp[revenue_col].cumsum() / (total_revenue or 1)) * 100
            pareto_data = prod_grp.head(10).to_dict(orient='records')

        kde_x, kde_y = [], []
        vals = self.df[revenue_col].dropna().values
        if len(vals) > 1:
            vals = vals[vals > 0]
            if len(vals) > 1:
                counts, bin_edges = np.histogram(vals, bins=25, density=True)
                kde_x = [round(float(x), 2) for x in bin_edges[:-1]]
                kde_y = [round(float(y), 6) for y in counts]

        seller_data = []
        if seller_col in self.df.columns:
            sellers = self.df.groupby(seller_col)[revenue_col].sum().reset_index()
            for _, r in sellers.iterrows():
                actual = float(r[revenue_col])
                target = round(actual * 1.15, 2)
                seller_data.append({"seller": str(r[seller_col]), "actual": actual, "target": target})

        category_data = []
        if category_col in self.df.columns:
            cat_grp = self.df.groupby(category_col)[revenue_col].sum().reset_index()
            category_data = [{"name": str(r[category_col]), "value": float(r[revenue_col])} for _, r in
                             cat_grp.iterrows()]

        top_seller_val = seller_data[0]['seller'] if seller_data else "Mavjud emas"
        top_product_val = pareto_data[0][product_col] if pareto_data else "Mavjud emas"

        meta_prod = str(product_col).capitalize().replace('_', ' ')
        meta_rev = str(revenue_col).capitalize().replace('_', ' ')
        meta_sell = str(seller_col).capitalize().replace('_', ' ')
        meta_cat = str(category_col).capitalize().replace('_', ' ')

        return {
            "kpi": {
                "total_revenue": total_revenue,
                "transactions": total_tx,
                "avg_check": round(avg_check, 2),
                "top_seller": top_seller_val,
                "top_product": top_product_val
            },
            "metadata": {
                "product_title": meta_prod,
                "revenue_title": meta_rev,
                "seller_title": meta_sell,
                "category_title": meta_cat
            },
            "table_columns": cols,
            "table_data": self.df.head(50).fillna("").astype(str).to_dict(orient='records'),
            "pareto": pareto_data,
            "kde": {"x": kde_x, "y": kde_y},
            "sellers": seller_data,
            "categories": category_data,
            "product_col": product_col,
            "revenue_col": revenue_col
        }
