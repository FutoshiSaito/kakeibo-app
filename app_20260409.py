from flask import Flask, render_template, request, redirect, session
import mysql.connector

app = Flask(__name__)
app.secret_key = "super-secret-key-12345"

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="kakeibo",
        password="T-weckl12345",
        database="kakeibo"
    )

@app.route("/")
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    selected_user = session.get("selected_user")

    return render_template("form.html", users=users, selected_user=selected_user)

@app.route("/add", methods=["POST"])
def add():
    date = request.form["date"]
    category = request.form["category"]
    amount = request.form["amount"]
    type_ = request.form["type"]
    memo = request.form["memo"]
    user_id = request.form['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
        INSERT INTO transactions (user_id, date, category, amount, type, memo)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
    cursor.execute(sql, (user_id, date, category, amount, type_, memo))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/list")

@app.route("/list", methods=["GET", "POST"])
def list_records():
    selected_user = session.get("selected_user")

    if request.method == "POST":
        selected_user = request.form.get("user_id")
        session["selected_user"] = selected_user

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, username FROM users")
    users = cursor.fetchall()

    if selected_user:
        # 特定ユーザの一覧
        cursor.execute("""
                       SELECT id, date, category, amount, type, memo
                       FROM transactions
                       WHERE user_id = %s
                       ORDER BY date DESC
                       """, (selected_user,))
    else:
        # 全ユーザの一覧
        cursor.execute("""
                       SELECT id, date, category, amount, type, memo
                       FROM transactions
                       ORDER BY date DESC
                       """)
    
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("list.html", rows=rows, users=users, selected_user=selected_user)

@app.route("/monthly-summary")
def monthly_summary():
    month = request.args.get("month")   # 例：2026-03
    user_id = request.args.get("user_id") # 例：1

    # 選択されたユーザーを覚えておく
    session["selected_user"] = user_id

    conn = get_db_connection()
    cursor = conn.cursor()

    # --- 支出合計 ---
    if user_id:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date LIKE %s AND user_id = %s AND type = '支出'
                       """, (month + "%", user_id))
    else:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date LIKE %s AND type = '支出'
                       """, (month + "%",))
    expense_total = cursor.fetchone()[0] or 0

    # --- 収入合計 ---
    if user_id:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date LIKE %s AND user_id = %s AND type = '収入'
                       """, (month + "%", user_id))
    else:
        cursor.execute("""
                       SELECT SUM(amount) FROM transactions
                       WHERE date LIKE %s AND type = '収入'
                       """, (month + "%",))
    income_total = cursor.fetchone()[0] or 0

    # --- カテゴリ別集計 ---
    if user_id:
        # 特定ユーザーの集計

        cursor.execute("""
                       SELECT category, SUM(amount)
                       FROM transactions
                       WHERE date LIKE %s AND user_id = %s
                       GROUP BY category
                       """, (month + "%", user_id))
    else:
        #全ユーザーの集計

        cursor.execute("""
                       SELECT category, SUM(amount)
                       FROM transactions
                       WHERE date LIKE %s
                       GROUP BY category
                       """, (month + "%",))
        
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()

    balance = income_total - expense_total

    return render_template(
        "monthly_summary.html",
        rows=rows,
        month=month,
        user_id=user_id,
        income_total=income_total,
        expense_total=expense_total,
        balance=balance
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

@app.route("/delete/<int:id>")
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

    # IDのデータを1件取得

    cursor.execute("""
                   SELECT id, date, category, amount, type, memo
                   FROM transactions
                   WHERE id = %s
                   """, (id,))
    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template("edit.html", row=row)

@app.route("/update/<int:id>", methods=["POST"])
def update(id):
    date = request.form["date"]
    category = request.form["category"]
    amount = request.form["amount"]
    type_ = request.form["type"]
    memo = request.form["memo"]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
                   UPDATE transactions
                   SET date = %s,
                   category = %s,
                   amount = %s,
                   type = %s,
                   memo = %s
                   WHERE id = %s
                   """, (date, category, amount, type_, memo, id))
    
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


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)