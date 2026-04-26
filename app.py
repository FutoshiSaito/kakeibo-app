from flask import Flask, render_template, request, redirect, session
from datetime import datetime
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
    type_ = request.form["type"]
    memo = request.form["memo"]
    user_id = request.form['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
        INSERT INTO transactions (user_id, date, category_id, amount, type, memo)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
    cursor.execute(sql, (user_id, date, category_id, amount, type_, memo))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/list")

@app.route("/add", methods=["GET"])
def add_form():
    user_id = request.args.get("user_id", None)

    conn = get_db_connection()
    cursor = conn.cursor()

    # ユーザー覧
    cursor.execute("SELECT id, username FROM users")
    users = cursor.fetchall()

    #カテゴリ一覧
    if user_id:
        cursor.execute("""
                    SELECT id, name FROM categories
                    WHERE user_id IS NULL OR user_id = %s
                    """, (user_id,))
    else:
        cursor.execute("""
                       SELECT id, name FROM categories
                       WHERE user_id IS NULL
                       ORDER BY name
                       """)
    categories = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("add.html", users=users, categories=categories, selected_user_id=user_id)

@app.route("/list", methods=["GET", "POST"])
def list_records():
    selected_user = session.get("selected_user")

    if request.method == "POST":
        selected_user = request.form.get("user_id")
        session["selected_user"] = selected_user

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, username FROM users")
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
                    SELECT t.id, t.date, t.type, t.amount, t.memo, u.username, c.name AS category_name
                    FROM transactions t
                    LEFT JOIN users u ON t.user_id = u.id
                    LEFT JOIN categories c ON t.category_id = c.id
                    WHERE (t.user_id = %s OR %s IS NULL)
                    ORDER BY t.date DESC
                    """, (selected_user, selected_user))

    
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

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
    end_date =  datetime(year, mon, 24)

    # --- 支出合計 ---
    if user_id:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date BETWEEN %s AND %s AND user_id = %s AND type = '支出'
                       """, (start_date, end_date, user_id))
    else:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date BETWEEN %s AND %s AND type = '支出'
                       """, (start_date, end_date))
    expense_total = cursor.fetchone()[0] or 0

    # --- 収入合計 ---
    if user_id:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date BETWEEN %s AND %s AND user_id = %s AND type = '収入'
                       """, (start_date, end_date, user_id))
    else:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date BETWEEN %s AND %s AND type = '収入'
                       """, (start_date, end_date))
    income_total = cursor.fetchone()[0] or 0

    # --- カテゴリ別集計 ---
    if user_id:
        # 特定ユーザーの集計
        cursor.execute("""
                       SELECT c.name AS category_name, SUM(t.amount)
                       FROM transactions t
                       LEFT JOIN categories c ON t.category_id = c.id
                       WHERE t.date BETWEEN %s AND %s AND t.user_id = %s
                       GROUP BY t.category_id
                       ORDER BY category_name
                       """, (start_date, end_date, user_id))
    else:
        #全ユーザーの集計
        cursor.execute("""
                       SELECT c.name AS category_name, SUM(t.amount)
                       FROM transactions t
                       LEFT JOIN categories c ON t.category_id = c.id
                       WHERE date BETWEEN %s AND %s
                       GROUP BY t.category_id
                       ORDER BY category_name
                       """, (start_date, end_date))
        
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()

    balance = income_total - expense_total

    return render_template(
        "monthly_summary.html",
        rows=rows,
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

    cursor.execute("SELECT id, username FROM users")
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    selected_user = session.get("selected_user")

    return render_template("select_month.html", users=users, selected_user=selected_user)

@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM transactions WHERE id = %s", (id,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/list")

@app.route("/edit/<int:id>")
def edit(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 編集対象の1件を取得

    cursor.execute("""
                   SELECT id, date, category_id, amount, type, memo, user_id
                   FROM transactions
                   WHERE id = %s
                   """, (id,))
    row = cursor.fetchone()
    # row = (id, date, category_id, amount, type, memo, user_id)

    # カテゴリ一覧を取得（共通＋該当ユーザーのカテゴリ）
    cursor.execute("""
                   SELECT id, name FROM categories
                   WHERE user_id IS NULL OR user_id = %s
                   ORDER BY name
                   """, (row[6],)) # row[6] = user_id
    categories = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("edit.html", row=row, categories=categories)

@app.route("/update/<int:id>", methods=["POST"])
def update(id):
    
    print("FORM DATA:", request.form)

    date = request.form["date"]
    category_id = request.form["category_id"]
    amount = request.form["amount"]
    type_ = request.form["type"]
    memo = request.form["memo"]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
                   UPDATE transactions
                   SET date = %s,
                       category_id = %s,
                       amount = %s,
                       type = %s,
                       memo = %s
                   WHERE id = %s
                   """, (date, category_id, amount, type_, memo, id))
    
    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/list")

@app.route("/add-user", methods=["GET", "POST"])
def add_user():
    if request.method == "POST":
        username = request.form["username"]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("INSERT INTO users (username) VALUES (%s)", (username,))
        conn.commit()

        cursor.close()
        conn.close()
        
        return redirect("/select-month") # 登録後は月別集計画面へ

    return render_template("add_user.html")

@app.route("/add-category", methods=["GET", "POST"])
def add_category():
    conn = get_db_connection()
    cursor = conn.cursor()

    # GET のときはユーザー一覧を渡す
    if request.method == "GET":
        cursor.execute("SELECT id, username FROM users")
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template("add_category.html", users=users)

    # POST のとき
    name = request.form["name"]
    user_id = request.form["user_id"] 
    
    if user_id == "":
        user_id = None   # 空なら共通カテゴリ
    else:
        user_id = int(user_id)

    # 重複チェック
    cursor.execute(
        "SELECT COUNT(*) FROM categories WHERE name = %s AND (user_id = %s OR user_id IS NULL)",
            (name, user_id)
    )
    exists = cursor.fetchone()[0]

    if exists > 0:
        cursor.close()
        conn.close()
        return "同じ名前のカテゴリがすでに存在します。"

    # カテゴリ追加
    cursor.execute(
        "INSERT INTO categories (name, user_id) VALUES (%s, %s)",
        (name, user_id)
    )
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/categories")
    
@app.route("/categories")
def categories_list():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
                   SELECT c.id, c.name, u.username
                   FROM categories c
                   LEFT JOIN users u ON c.user_id = u.id
                   ORDER BY u.username IS NOT NULL, u.username, c.name
                   """)
    categories = cursor.fetchall()

    # print("=== DEBUG categories ===")
    # for row in categories:
    #     print(row)
    # print("========================")

    cursor.close()
    conn.close()

    return render_template("categories.html", categories=categories)

@app.route("/delete-category/<int:category_id>")
def delete_category(category_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # まず、そのカテゴリが transactions で使われていないか確認
    cursor.execute("""
                   SELECT COUNT(*) FROM transactions WHERE category = (
                        SELECT name FROM categories WHERE id = %s
                   )
                   """, (category_id,))
    count = cursor.fetchone()[0]

    if count > 0:
        cursor.close()
        conn.close()
        return "このカテゴリは使用されているので削除できません。"
    
    # 使われていなければ削除
    cursor.execute("DELETE FROM categories WHERE id = %s", (category_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/categories")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)