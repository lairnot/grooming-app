from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "grooming.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "groomies-dev-secret-key")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error: Optional[BaseException]) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            whatsapp TEXT,
            address TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            species TEXT NOT NULL,
            breed TEXT,
            age TEXT,
            weight TEXT,
            temperament TEXT,
            medical_notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );

        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            duration_minutes INTEGER NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            pet_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Agendada',
            groomer TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id),
            FOREIGN KEY (pet_id) REFERENCES pets(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
        """
    )

    admin_exists = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not admin_exists:
        db.execute(
            "INSERT INTO users (username, password_hash, full_name) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("groomies123"), "Administrador Groomies"),
        )

    services_count = db.execute("SELECT COUNT(*) AS count FROM services").fetchone()["count"]
    if services_count == 0:
        seed_services = [
            ("Baño", 250, 60, "Baño básico con secado."),
            ("Baño y corte", 420, 90, "Baño completo con corte estético."),
            ("Deslanado", 380, 75, "Retiro de pelo muerto."),
            ("Baño medicado", 330, 60, "Incluye shampoo terapéutico."),
            ("Corte de uñas", 80, 15, "Recorte de uñas."),
        ]
        db.executemany(
            "INSERT INTO services (name, price, duration_minutes, description) VALUES (?, ?, ?, ?)",
            seed_services,
        )
    db.commit()


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            return redirect(url_for("dashboard"))

        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    stats = {
        "clients": db.execute("SELECT COUNT(*) AS total FROM clients").fetchone()["total"],
        "pets": db.execute("SELECT COUNT(*) AS total FROM pets").fetchone()["total"],
        "today_appointments": db.execute(
            "SELECT COUNT(*) AS total FROM appointments WHERE appointment_date = ?", (today,)
        ).fetchone()["total"],
        "services": db.execute("SELECT COUNT(*) AS total FROM services").fetchone()["total"],
    }
    upcoming = db.execute(
        """
        SELECT a.id, a.appointment_date, a.appointment_time, a.status,
               c.name AS client_name, p.name AS pet_name, s.name AS service_name
        FROM appointments a
        JOIN clients c ON c.id = a.client_id
        JOIN pets p ON p.id = a.pet_id
        JOIN services s ON s.id = a.service_id
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
        LIMIT 8
        """
    ).fetchall()
    return render_template("dashboard.html", stats=stats, upcoming=upcoming)


@app.route("/clients", methods=["GET", "POST"])
@login_required
def clients():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        whatsapp = request.form.get("whatsapp", "").strip()
        address = request.form.get("address", "").strip()

        if not name or not phone:
            flash("Nombre y teléfono son obligatorios.", "error")
        else:
            db.execute(
                "INSERT INTO clients (name, phone, whatsapp, address, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, phone, whatsapp, address, datetime.now().isoformat(timespec="seconds")),
            )
            db.commit()
            flash("Cliente registrado correctamente.", "success")
            return redirect(url_for("clients"))

    client_rows = db.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
    return render_template("clients.html", clients=client_rows)


@app.route("/pets", methods=["GET", "POST"])
@login_required
def pets():
    db = get_db()
    clients_list = db.execute("SELECT id, name FROM clients ORDER BY name ASC").fetchall()

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        name = request.form.get("name", "").strip()
        species = request.form.get("species", "").strip()
        breed = request.form.get("breed", "").strip()
        age = request.form.get("age", "").strip()
        weight = request.form.get("weight", "").strip()
        temperament = request.form.get("temperament", "").strip()
        medical_notes = request.form.get("medical_notes", "").strip()

        if not client_id or not name or not species:
            flash("Cliente, nombre y especie son obligatorios.", "error")
        else:
            db.execute(
                """
                INSERT INTO pets
                (client_id, name, species, breed, age, weight, temperament, medical_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    name,
                    species,
                    breed,
                    age,
                    weight,
                    temperament,
                    medical_notes,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()
            flash("Mascota registrada correctamente.", "success")
            return redirect(url_for("pets"))

    pet_rows = db.execute(
        """
        SELECT p.*, c.name AS client_name
        FROM pets p
        JOIN clients c ON c.id = p.client_id
        ORDER BY p.id DESC
        """
    ).fetchall()
    return render_template("pets.html", pets=pet_rows, clients=clients_list)


@app.route("/appointments", methods=["GET", "POST"])
@login_required
def appointments():
    db = get_db()
    clients_list = db.execute("SELECT id, name FROM clients ORDER BY name ASC").fetchall()
    pets_list = db.execute("SELECT id, name FROM pets ORDER BY name ASC").fetchall()
    services_list = db.execute("SELECT id, name, price FROM services ORDER BY name ASC").fetchall()

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        pet_id = request.form.get("pet_id", "").strip()
        service_id = request.form.get("service_id", "").strip()
        appointment_date = request.form.get("appointment_date", "").strip()
        appointment_time = request.form.get("appointment_time", "").strip()
        status = request.form.get("status", "Agendada").strip()
        groomer = request.form.get("groomer", "").strip()
        notes = request.form.get("notes", "").strip()

        if not all([client_id, pet_id, service_id, appointment_date, appointment_time]):
            flash("Cliente, mascota, servicio, fecha y hora son obligatorios.", "error")
        else:
            db.execute(
                """
                INSERT INTO appointments
                (client_id, pet_id, service_id, appointment_date, appointment_time, status, groomer, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    pet_id,
                    service_id,
                    appointment_date,
                    appointment_time,
                    status,
                    groomer,
                    notes,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()
            flash("Cita creada correctamente.", "success")
            return redirect(url_for("appointments"))

    appointment_rows = db.execute(
        """
        SELECT a.*, c.name AS client_name, p.name AS pet_name,
               s.name AS service_name, s.price AS service_price
        FROM appointments a
        JOIN clients c ON c.id = a.client_id
        JOIN pets p ON p.id = a.pet_id
        JOIN services s ON s.id = a.service_id
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
        """
    ).fetchall()
    return render_template(
        "appointments.html",
        appointments=appointment_rows,
        clients=clients_list,
        pets=pets_list,
        services=services_list,
    )


@app.route("/services", methods=["GET", "POST"])
@login_required
def services():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", "").strip()
        duration_minutes = request.form.get("duration_minutes", "").strip()
        description = request.form.get("description", "").strip()
        if not name or not price or not duration_minutes:
            flash("Nombre, precio y duración son obligatorios.", "error")
        else:
            db.execute(
                "INSERT INTO services (name, price, duration_minutes, description) VALUES (?, ?, ?, ?)",
                (name, float(price), int(duration_minutes), description),
            )
            db.commit()
            flash("Servicio agregado correctamente.", "success")
            return redirect(url_for("services"))

    service_rows = db.execute("SELECT * FROM services ORDER BY id DESC").fetchall()
    return render_template("services.html", services=service_rows)


@app.context_processor
def inject_now():
    return {"now": datetime.now()}


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
