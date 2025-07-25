from flask import Flask, render_template, request, redirect, url_for, send_file, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate  # Importar Flask-Migrate
from gtts import gTTS
import os
import uuid
import stripe
import openai
from dotenv import load_dotenv

load_dotenv()

# Inicialización de Flask y configuración
app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatbot.db'  # Conexión a la base de datos
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Desactivar advertencia de modificaciones
db = SQLAlchemy(app)
migrate = Migrate(app, db)  # Configuración de Flask-Migrate

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")

# Modelos de base de datos
class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)  # Campo para el correo electrónico
    is_premium = db.Column(db.Boolean, default=False)
    questions_used = db.Column(db.Integer, default=0)
    images_used = db.Column(db.Integer, default=0)

# Crear las tablas si no existen (solo para el inicio)
with app.app_context():
    db.create_all()

@app.before_request
def assign_session():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
        # Verificar si el usuario ya existe en la base de datos
        if not User.query.filter_by(session_id=session['user_id']).first():
            db.session.add(User(session_id=session['user_id']))
            db.session.commit()

@app.route('/')
def home():
    history = ChatHistory.query.all()
    user = User.query.filter_by(session_id=session.get('user_id')).first()
    return render_template('index.html', chat_history=history, user=user)

@app.route('/ask', methods=['POST'])
def ask():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())

    user = User.query.filter_by(session_id=session['user_id']).first()
    if not user:
        user = User(session_id=session['user_id'])
        db.session.add(user)
        db.session.commit()

    if not user.is_premium and user.questions_used >= 10:
        return "Límite gratuito alcanzado. Suscríbete para más."

    question = request.form['question']
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "Eres H.IA, un asistente de estudios útil."},
                      {"role": "user", "content": question}]
        )
        answer = response.choices[0].message["content"]
    except Exception as e:
        return f"Error al consultar OpenAI: {e}", 500

    db.session.add(ChatHistory(question=question, answer=answer))
    user.questions_used += 1
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/reset')
def reset():
    ChatHistory.query.delete()
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/generate_audio', methods=['POST'])
def generate_audio():
    user = User.query.filter_by(session_id=session['user_id']).first()
    if not user or not user.is_premium:
        return "Función premium. Suscríbete."

    text = request.form['text']
    tts = gTTS(text, lang='es')
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join("static", "audios", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tts.save(filepath)
    return send_file(filepath, as_attachment=True)

@app.route('/generate_image', methods=['POST'])
def generate_image():
    user = User.query.filter_by(session_id=session['user_id']).first()
    if not user or (not user.is_premium and user.images_used >= 2):
        return "Límite gratuito alcanzado. Suscríbete para más."

    prompt = request.form['prompt']
    try:
        response = openai.Image.create(
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        image_url = response["data"][0]["url"]
        user.images_used += 1
        db.session.commit()

        return render_template('chat.html', image_url=image_url)  # Pasar la URL a la plantilla
    except Exception as e:
        return f"Error generando imagen: {str(e)}", 500

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    if file:
        upload_dir = os.path.join("uploads")
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, file.filename)
        file.save(filepath)
        return f"Archivo {file.filename} subido correctamente."
    return "No se seleccionó ningún archivo."

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form['email']
    checkout_session = stripe.checkout.Session.create(
        customer_email=email,
        payment_method_types=['card'],
        line_items=[{
            'price': STRIPE_PRICE_ID,
            'quantity': 1,
        }],
        mode='subscription',
        success_url=url_for('activate_premium', _external=True),
        cancel_url=url_for('home', _external=True),
    )
    return redirect(checkout_session.url, code=303)

@app.route('/premium')
def activate_premium():
    user = User.query.filter_by(session_id=session['user_id']).first()
    if user:
        user.is_premium = True
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Si el formulario ha sido enviado con un correo
    if request.method == 'POST':
        email = request.form['email']
        session['email'] = email  # Guardar el correo en la sesión

        # Verificar si ya existe el usuario
        user = User.query.filter_by(session_id=session['user_id']).first()
        if not user:
            # Si el usuario no existe, lo creamos con el correo
            user = User(session_id=session['user_id'], email=email)
            db.session.add(user)
            db.session.commit()

        # Inicializamos las 10 preguntas y 2 imágenes gratuitas
        if not user.questions_used and not user.images_used:
            user.questions_used = 0  # Preguntas disponibles
            user.images_used = 0  # Imágenes disponibles
            db.session.commit()

        return redirect(url_for('home'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)