import matplotlib

matplotlib.use('Agg')  # Headless server muhiti uchun
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import os


class HDExporter:
    @staticmethod
    def generate_4k_png(data):
        os.makedirs("exports", exist_ok=True)
        path = "exports/dashboard_4k.png"

        # 4K O'lcham: 3840x2160 (12.8 x 7.2 dyuym 300 DPI da)
        fig = plt.figure(figsize=(12.8, 7.2), dpi=300, facecolor='#F8FAFC')
        fig.suptitle("SMART ANALYTICS ENGINE — 4K EXECUTIVE DASHBOARD", fontsize=16, fontweight='bold', color='#1E293B',
                     y=0.96)

        gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.25, left=0.08, right=0.95, top=0.88, bottom=0.08)

        # 1. Pareto Chart
        ax1 = fig.add_subplot(gs[0, 0])
        pareto = data.get('pareto', [])[:5]
        prod_col = data.get('product_col', 'Mahsulot')
        rev_col = data.get('revenue_col', 'Tushum')
        names = [str(p.get(prod_col, ''))[:10] for p in pareto]
        vals = [p.get(rev_col, 0) for p in pareto]

        ax1.bar(names, vals, color='#2563EB', width=0.5)
        ax1.set_title("Top Mahsulotlar (Tushum)", fontsize=11, fontweight='bold', color='#334155', pad=8)
        ax1.tick_params(colors='#64748B', labelsize=8)
        ax1.grid(axis='y', linestyle='--', alpha=0.3)
        ax1.set_facecolor('#FFFFFF')

        # 2. KDE / Zichlik Grafik
        ax2 = fig.add_subplot(gs[0, 1])
        kde = data.get('kde', {'x': [], 'y': []})
        ax2.plot(kde['x'], kde['y'], color='#F59E0B', linewidth=2.5)
        ax2.fill_between(kde['x'], kde['y'], color='#F59E0B', alpha=0.2)
        ax2.set_title("Tushum Zichlik Darajasi", fontsize=11, fontweight='bold', color='#334155', pad=8)
        ax2.tick_params(colors='#64748B', labelsize=8)
        ax2.grid(linestyle='--', alpha=0.3)
        ax2.set_facecolor('#FFFFFF')

        # 3. Seller Chart
        ax3 = fig.add_subplot(gs[1, 0])
        sellers = data.get('sellers', [])[:5]
        s_names = [str(s.get('seller', ''))[:10] for s in sellers]
        s_act = [s.get('actual', 0) for s in sellers]
        s_tar = [s.get('target', 0) for s in sellers]
        y_pos = list(range(len(s_names)))

        ax3.barh([p - 0.15 for p in y_pos], s_act, height=0.3, color='#10B981', label='Amalda')
        ax3.barh([p + 0.15 for p in y_pos], s_tar, height=0.3, color='#CBD5E1', label='Reja')
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(s_names)
        ax3.set_title("Sotuvchilar: Reja va Amal", fontsize=11, fontweight='bold', color='#334155', pad=8)
        ax3.legend(loc='lower right', fontsize=7)
        ax3.tick_params(colors='#64748B', labelsize=8)
        ax3.set_facecolor('#FFFFFF')

        # 4. Category Pie Chart
        ax4 = fig.add_subplot(gs[1, 1])
        cats = data.get('categories', [])[:5]
        c_labels = [c.get('name', '') for c in cats]
        c_vals = [c.get('value', 0) for c in cats]
        if sum(c_vals) > 0:
            ax4.pie(c_vals, labels=c_labels, autopct='%1.1f%%',
                    colors=['#2563EB', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899'],
                    textprops={'fontsize': 8, 'color': '#334155'})
        ax4.set_title("Kategoriyalar Ulushi", fontsize=11, fontweight='bold', color='#334155', pad=8)

        plt.savefig(path, dpi=300, facecolor=fig.get_facecolor(), bbox_inches='tight')
        plt.close()
        return path

    @staticmethod
    def generate_4k_video(data):
        os.makedirs("exports", exist_ok=True)
        path = "exports/analytics_4k.mp4"

        fig = plt.figure(figsize=(12.8, 7.2), dpi=150, facecolor='#F8FAFC')
        gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.25, left=0.08, right=0.95, top=0.88, bottom=0.08)

        pareto = data.get('pareto', [])[:5]
        prod_col = data.get('product_col', 'Mahsulot')
        rev_col = data.get('revenue_col', 'Tushum')
        names = [str(p.get(prod_col, ''))[:10] for p in pareto]
        vals = [p.get(rev_col, 0) for p in pareto]

        ax1 = fig.add_subplot(gs[0, 0])
        frames = 30

        def update(frame):
            ax1.clear()
            ax1.set_title("Top Mahsulotlar (4K Animatsiya)", fontsize=11, fontweight='bold', color='#334155')
            ax1.grid(axis='y', linestyle='--', alpha=0.3)
            current_vals = [v * (frame + 1) / frames for v in vals]
            ax1.bar(names, current_vals, color='#2563EB', width=0.5)
            ax1.tick_params(colors='#64748B', labelsize=8)

        ani = animation.FuncAnimation(fig, update, frames=frames, interval=80)

        try:
            writer = animation.FFmpegWriter(fps=15, metadata=dict(artist='Smart Analytics'), bitrate=1800)
            ani.save(path, writer=writer)
        except Exception:
            # FFmpeg bo'lmaganda Pillow / GIF/MP4 moslashuvchan fallback
            ani.save(path, writer='pillow', fps=15)

        plt.close()
        return path
