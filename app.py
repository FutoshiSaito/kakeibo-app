from flask import Flask, render_template, request, redirect, session
from datetime import datetime, date
import os
import mysql.connector

app = Flask(__name__)
app.secret_key = "super-secret-key-12345"

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD",""),
        database=os.getenv("DB_NAME","kakeibo")
    )

@app.route("/")
def index():
    return redirect("/list")

@app.route("/add", methods=["POST"])
def add():
    date = request.form["date"]
    category_id = request.form["category_id"]
    amount = request.form["amount"]
    memo = request.form["memo"]
    user_id = request.form["user_id"]
    payment_method_id = request.form.get("payment_method_id")

    conn = get_db_connection()
    cursor = conn.cursor()

    # ★ カテゴリから type（収入/支出）を取得
    cursor.execute("SELECT type FROM categories WHERE id = %s", (category_id,))
    category_type = cursor.fetchone()[0]

    # ★ 収入なら payment_method_id を None にする
    if category_type == "収入":
        payment_method_id = None

    # ★ INSERT（payment_method_id を追加）
    sql = """
        INSERT INTO transactions (user_id, date, category_id, payment_method_id, amount, memo)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    cursor.execute(sql, (user_id, date, category_id, payment_method_id, amount, memo))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/list")


@app.route("/add", methods=["GET"])
def add_form():
    user_id = request.args.get("user_id", None)
    if not user_id:
        user_id = session.get("selected_user")

    type_value = request.args.get("type", None)
    if not type_value:
        type_value = "支出"

    date_value = request.args.get("date", "")
    if not date_value:
        date_value = date.today().strftime("%Y-%m-%d")


    conn = get_db_connection()
    cursor = conn.cursor()

    # ユーザー覧
    cursor.execute("SELECT id, username FROM users ORDER BY id")
    users = cursor.fetchall()

    # ★ 決済手段一覧（追加）
    cursor.execute("SELECT id, name FROM payment_methods ORDER BY sort_order")
    payment_methods = cursor.fetchall()

    default_pm_id = None
    for pm in payment_methods:
        if pm[1].lower() == "card":
            default_pm_id = pm[0]
            break

    #カテゴリ一覧
    if user_id and type_value:
        cursor.execute("""
                    SELECT id, name FROM categories
                    WHERE (user_id IS NULL OR user_id = %s) AND type = %s
                    ORDER BY name
                    """, (user_id, type_value))
    
    elif user_id:
        cursor.execute("""
            SELECT id, name FROM categories
            WHERE user_id IS NULL OR user_id = %s
            ORDER BY name
        """, (user_id,))

    elif type_value:
        cursor.execute("""
            SELECT id, name FROM categories
            WHERE user_id IS NULL
              AND type = %s
            ORDER BY name
        """, (type_value,))

    else:
        cursor.execute("""
                       SELECT id, name FROM categories
                       WHERE user_id IS NULL
                       ORDER BY name
                       """)
    categories = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "add.html",
        users=users,
        categories=categories,
        payment_methods=payment_methods,
        selected_user_id=user_id,
        selected_type=type_value,
        selected_date=date_value,
        selected_payment_method_id = default_pm_id
        )

@app.route("/list", methods=["GET", "POST"])
def list_records():
    selected_user = session.get("selected_user")

    if request.method == "POST":
        selected_user = request.form.get("user_id")
        session["selected_user"] = selected_user

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, username FROM users ORDER BY id")
    users = cursor.fetchall()

    # print("selected_user =", selected_user, type(selected_user))
    print("RAW user_id =", request.args.get("user_id"))


    selected_user = request.args.get("user_id")

    # ここで正規化（超重要）
    if selected_user is None or selected_user == "":
        selected_user = None
    else:
        selected_user = int(selected_user)

    cursor.execute("""
        SELECT 
            t.id,
            t.date,
            c.type AS category_type,      -- ★ 収入 / 支出（カテゴリから取得）
            t.amount,
            t.memo,
            u.username,
            c.name AS category_name,
            pm.name AS payment_method_name
        FROM transactions t
        LEFT JOIN users u ON t.user_id = u.id
        LEFT JOIN categories c ON t.category_id = c.id
        LEFT JOIN payment_methods pm ON t.payment_method_id = pm.id
        WHERE (t.user_id = %s OR %s IS NULL)
        ORDER BY t.date DESC
    """, (selected_user, selected_user))
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    def calc_group_index(date_obj):
        # 25日締めの月グループを計算
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        # 25日より前なら前月扱い
        if day < 25:
            if month == 1:
                year -= 1
                month = 12
            else:
                month -= 1

        # 年×12 + 月 で一意の番号にする
        return int(year * 12 + month)

    from datetime import datetime
    for row in rows:
        date_obj = row["date"]  # datetime.date 型
        row["group_index"] = calc_group_index(date_obj)

    return render_template("list.html", rows=rows, users=users, selected_user=selected_user)

@app.route("/monthly-summary")
def monthly_summary():
    conn = get_db_connection()
    cursor = conn.cursor()

    month = request.args.get("month")   # 例：2026-03
    user_id = request.args.get("user_id") # 例：1
    username = None
    if user_id:
        cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            username = result[0]

    # 選択されたユーザーを覚えておく
    session["selected_user"] = user_id

    # --- 期間計算（締め日25日方式） ---
    year = int(month.split("-")[0])
    mon = int(month.split("-")[1])

    # 前月計算
    if mon == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = mon - 1

    # 開始日：前月25日
    start_date = datetime(prev_year, prev_month, 25)
    # 終了日：当月24日
    end_date = datetime(year, mon, 24)

    # --- 支出合計（categories.type = '支出'） ---
    if user_id:
        cursor.execute("""
            SELECT COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.date BETWEEN %s AND %s
              AND t.user_id = %s
              AND c.type = '支出'
        """, (start_date, end_date, user_id))
    else:
        cursor.execute("""
            SELECT COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.date BETWEEN %s AND %s
              AND c.type = '支出'
        """, (start_date, end_date))
    expense_total = cursor.fetchone()[0]

    # --- 収入合計（categories.type = '収入'） ---
    if user_id:
        cursor.execute("""
            SELECT COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.date BETWEEN %s AND %s
              AND t.user_id = %s
              AND c.type = '収入'
        """, (start_date, end_date, user_id))
    else:
        cursor.execute("""
            SELECT COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.date BETWEEN %s AND %s
              AND c.type = '収入'
        """, (start_date, end_date))
    income_total = cursor.fetchone()[0]

    # --- カテゴリ別集計（categories.type を使用） ---
    if user_id:
        cursor.execute("""
            SELECT c.name AS category_name, c.type AS category_type, SUM(t.amount)
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.date BETWEEN %s AND %s
              AND t.user_id = %s
            GROUP BY c.id
            ORDER BY 2, 1   -- 2->category_name, 1->category_type
        """, (start_date, end_date, user_id))
    else:
        cursor.execute("""
            SELECT c.name AS category_name, c.type AS category_type, SUM(t.amount)
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.date BETWEEN %s AND %s
            GROUP BY c.id
            ORDER BY 2, 1   -- 2->category_name, 1->category_type
        """, (start_date, end_date))
    category_rows = cursor.fetchall()

    # --- 決済手段別集計 ---
    if user_id:
        cursor.execute("""
            SELECT 
                pm.name AS payment_method,
                SUM(t.amount) AS total_amount
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            LEFT JOIN payment_methods pm ON t.payment_method_id = pm.id
            WHERE t.date BETWEEN %s AND %s
            AND t.user_id = %s
            AND c.type = '支出'
            GROUP BY pm.id
            ORDER BY total_amount DESC
        """, (start_date, end_date, user_id))
    else:
        cursor.execute("""
            SELECT 
                pm.name AS payment_method,
                SUM(t.amount) AS total_amount
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            LEFT JOIN payment_methods pm ON t.payment_method_id = pm.id
            WHERE t.date BETWEEN %s AND %s
            AND c.type = '支出'
            GROUP BY pm.id
            ORDER BY total_amount DESC
        """, (start_date, end_date))
    payment_rows = cursor.fetchall()

    cursor.close()
    conn.close()

    balance = income_total - expense_total

    return render_template(
        "monthly_summary.html",
        category_rows=category_rows,
        payment_rows=payment_rows,
        month=month,
        user_id=user_id,
        username=username,
        income_total=income_total,
        expense_total=expense_total,
        balance=balance,
        start_date=start_date,
        end_date=end_date
    )

@app.route("/select-month", methods=["GET", "POST"])
def select_month():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, username FROM users ORDER BY id")
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    selected_user = session.get("selected_user")

    return render_template("select_month.html", users=users, selected_user=selected_user)

@app.route("/edit/<int:id>")
def edit(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 編集対象の1件を取得

    cursor.execute("""
                   SELECT id, date, category_id, amount, memo, user_id, payment_method_id
                   FROM transactions
                   WHERE id = %s
                   """, (id,))
    row = cursor.fetchone()
    # row = (id, date, category_id, amount, memo, user_id, payment_method_id)

    transaction_id = row[0]
    date = row[1]
    category_id = row[2]
    amount = row[3]
    memo = row[4]
    user_id = row[5]
    payment_method_id = row[6]

    # ★ このトランザクションのカテゴリの type を取得
    cursor.execute("SELECT type FROM categories WHERE id = %s", (category_id,))
    selected_type = cursor.fetchone()[0]   # '収入' or '支出'

    # カテゴリ一覧を取得（ユーザー + type で絞る）
    cursor.execute("""
                   SELECT id, name FROM categories
                   WHERE (user_id IS NULL OR user_id = %s) AND type = %s
                   ORDER BY name
                   """, (user_id, selected_type))
    categories = cursor.fetchall()

    # 決済手段一覧を取得
    cursor.execute("""
                   SELECT id, name FROM payment_methods ORDER BY sort_order
                   """)
    payment_methods = cursor.fetchall()


    cursor.close()
    conn.close()

    return render_template(
        "edit.html", 
        id=transaction_id,
        date=date,
        amount=amount,
        memo=memo,
        user_id=user_id,
        category_id=category_id,
        categories=categories,
        selected_type=selected_type,
        payment_method_id=payment_method_id,
        payment_methods=payment_methods
        )

@app.route("/update/<int:id>", methods=["POST"])
def update(id):

    print("FORM DATA:", request.form)

    date = request.form["date"]
    category_id = request.form["category_id"]
    amount = request.form["amount"]
    memo = request.form["memo"]
    user_id = request.form["user_id"]   # hidden で送られてくる
    payment_method_id = request.form.get("payment_method_id")

    conn = get_db_connection()
    cursor = conn.cursor()

    # ★ カテゴリから type（収入/支出）を取得
    cursor.execute("SELECT type FROM categories WHERE id = %s", (category_id,))
    category_type = cursor.fetchone()[0]

    # ★ 収入なら payment_method_id を None にする
    if category_type == "収入":
        payment_method_id = None

    # ★ UPDATE（type はフォームから受け取らず、category_type を使う）
    cursor.execute("""
        UPDATE transactions
        SET date = %s,
            category_id = %s,
            payment_method_id = %s,
            amount = %s,
            memo = %s,
            user_id = %s
        WHERE id = %s
    """, (date, category_id, payment_method_id, amount, memo, user_id, id))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/list")

@app.route("/admin/users/add", methods=["GET", "POST"])
def admin_user_add():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        username = request.form["username"]

        # 重複チェック
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE username = %s", (username,))
        exists = cursor.fetchone()["cnt"]

        if exists > 0:
            cursor.close()
            conn.close()
            return render_template(
                "admin_user_add.html",
                error="同じユーザー名がすでに存在します。",
                username=username
            )
        
        # 追加
        cursor.execute("INSERT INTO users (username) VALUES (%s)", (username,))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect("/admin")
    
    cursor.close()
    conn.close()
    return render_template("admin_user_add.html")

@app.route("/admin/users/edit/<int:user_id>", methods=["GET", "POST"])
def admin_user_edit(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if not user:
        cursor.close()
        conn.close()
        return "ユーザーが見つかりません。"
    
    if request.method == "POST":
        username = request.form["username"]

        # 重複チェック
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE username = %s AND id != %s", (username, user_id))
        exists = cursor.fetchone()["cnt"]

        if exists > 0:
            cursor.close()
            conn.close()
            return render_template(
                "admin_user_edit.html",
                user=user,
                error="同じユーザー名がすでに存在します。"
            )
        
        # 更新
        cursor.execute("UPDATE users SET username = %s WHERE id = %s", (username, user_id))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect("/admin")
    
    cursor.close()
    conn.close()
    return render_template("admin_user_edit.html", user=user)

@app.route("/admin/categories/add", methods=["GET", "POST"])
def admin_category_add():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        name = request.form["name"]
        type_ = request.form["type"]

        # 重複チェック
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM categories WHERE name = %s AND type = %s",
            (name, type_)
            )
        exists = cursor.fetchone()["cnt"]

        if exists > 0:
            cursor.close()
            conn.close()
            return render_template(
                "admin_category_add.html",
                error="同じカテゴリがすでに存在します。",
                name=name,
                type=type_
            )
        
        # 追加
        cursor.execute(
            "INSERT INTO categories (name, type) VALUES (%s, %s)",
            (name, type_)
        )
        conn.commit()

        cursor.close()
        conn.close()

        return redirect("/admin")
    
    # GET
    cursor.close()
    conn.close()
    return render_template("admin_category_add.html")

@app.route("/admin/categories/edit/<int:cat_id>", methods=["GET", "POST"])
def admin_categories_edit(cat_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # カテゴリ取得
    cursor.execute("SELECT * FROM categories WHERE id = %s", (cat_id,))
    category = cursor.fetchone()

    if not category:
        cursor.close()
        conn.close()
        return "カテゴリが見つかりません。"
    
    # POST（更新処理）
    if request.method == "POST":
        name = request.form["name"]
        type_ = request.form["type"]

        # 重複チェック
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM categories
            WHERE name = %s AND type = %s AND id != %s
            """,
            (name, type_, cat_id)
        )
        exists = cursor.fetchone()["cnt"]

        if exists > 0:
            cursor.close()
            conn.close()
            return render_template(
                "admin_category_edit.html",
                category=category,
                error="同じカテゴリがすでに存在します。"
            )
        
        # 更新
        cursor.execute(
            "UPDATE categories SET name = %s, type = %s WHERE id = %s",
            (name, type_, cat_id)
        )
        conn.commit()

        cursor.close()
        conn.close()

        return redirect("/admin")
    
    # GET（編集画面表示）
    cursor.close()
    conn.close()
    return render_template("admin_category_edit.html", category=category)

@app.route("/admin/categories/delete/<int:cat_id>", methods=["GET", "POST"])
def admin_category_delete(cat_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 使われているカテゴリは削除不可（安全）
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE category_id = %s", (cat_id,))
    used = cursor.fetchone()[0]

    if used > 0:
        cursor.close()
        conn.close()
        return "このカテゴリは使用されているため削除できません。"
    
    cursor.execute("DELETE FROM categories WHERE id = %s", (cat_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/admin")

@app.route("/admin/payments/add", methods=["GET", "POST"])
def admin_payment_add():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        name = request.form["name"]

        # 重複チェック
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payment_methods WHERE name = %s",
            (name,)
            )
        exists = cursor.fetchone()["cnt"]

        if exists > 0:
            cursor.close()
            conn.close()
            return render_template(
                "admin_payment_add.html",
                error="同じ決済手段がすでに存在します。",
                name=name
            )
        
        # sort_order を自動採番（最大値＋１）
        cursor.execute("SELECT COALESCE(MAX(sort_order), 0) AS max_order FROM payment_methods")
        max_order = cursor.fetchone()["max_order"]
        sort_order = max_order + 1
        
        # 追加
        cursor.execute(
            "INSERT INTO payment_methods (name, sort_order) VALUES (%s, %s)",
            (name, sort_order)
        )
        conn.commit()

        cursor.close()
        conn.close()

        return redirect("/admin")
    
    # GET
    cursor.close()
    conn.close()
    return render_template("admin_payment_add.html")

@app.route("/admin/payments/edit/<int:pay_id>")
def admin_payment_edit(pay_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 決済手段の取得
    cursor.execute("SELECT * FROM payment_methods WHERE id = %s", (pay_id,))
    payment = cursor.fetchone()

    if not payment:
        cursor.close()
        conn.close()
        return "決済手段が見つかりません。"
    
    # POST（更新処理）
    if request.method == "POST":
        name = request.form["name"]
        sort_order = request.form["sort_order"]

        # sort_oder が空なら None に
        if sort_order == "":
            sort_order = None
        else:
            sort_order = int(sort_order)

        # 重複チェック
        cursor.execute("""
                       SELECT COUNT(*) AS cnt"
                       FROM payment_methods
                       WHERE name = %s AND id != %s
                       """,
                       (name, pay_id)
                       )
        exists = cursor.fetchone()["cnt"]

        if exists > 0:
            cursor.close()
            conn.close()
            return render_template(
                "admin_payment_edit.html",
                payment=payment,
                error="同じ決済手段がすでに存在します。"
            )
        
        # 更新
        cursor.execute(
            "UPDATE payment_methods SET name = %s, sort_order = %s WHERE id = %s",
            (name, sort_order, pay_id)
        )
        conn.comitt()

        cursor.close()
        conn.close()

        return redirect("/admin")
    
    # GET（編集画面表示）
    cursor.close()
    conn.close()
    return render_template("admin_payment_edit.html", payment=payment)

@app.route("/admin/payments/delete/<int:pay_id>", methods=["POST"])
def admin_payment_delete(pay_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 使われている決済手段は削除不可
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE payment_method_id = %s", (pay_id,))
    used = cursor.fetchone()[0]

    if used > 0:
        cursor.close()
        conn.close()
        return "この決済手段は使用されているため削除できません。"
    
    cursor.execute("DELETE FROM payment_methods WHERE id = %s", (pay_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/admin")

@app.route("/admin")
def admin_home():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ユーザー一覧
    cursor.execute("SELECT id, username FROM users ORDER BY id")
    users = cursor.fetchall()

    # カテゴリ一覧
    cursor.execute("SELECT id, name, type FROM categories ORDER BY type, id")
    categories = cursor.fetchall()

    # 決済手段一覧
    cursor.execute("SELECT id, name, sort_order FROM payment_methods ORDER BY sort_order")
    payments = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "admin.html",
        users=users,
        categories=categories,
        payments=payments
        )



if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)