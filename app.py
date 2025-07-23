from flask import Flask, render_template, request, redirect, url_for, send_file, session
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI
from gtts import gTTS
import os
import uuid
import stripe
from dotenv import load_dotenv

# Cargar variables del archivo .env (útil para desarrollo local)
load_dotenv()

# Configuraciones
app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatbot.db'
db = SQLAlchemy(app)

# OpenAI (cliente moderno)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")

# Base de datos
class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    is_premium = db.Column(db.Boolean, default=False)
    questions_used = db.Column(db.Integer, default=0)
    images_used = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

@app.before_request
def assign_session():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
        if not User.query.filter_by(session_id=session['user_id']).first():
            db.session.add(User(session_id=session['user_id']))
            db.session.commit()

@app.route('/')
def home():
    history = ChatHistory.query.all()
    return render_template('index.html', chat_history=history)

@app.route('/ask', methods=['POST'])
def ask():
    user = User.query.filter_by(session_id=session['user_id']).first()
    if not user.is_premium and user.questions_used >= 10:
        return "Límite gratuito alcanzado. Suscríbete para preguntas ilimitadas."

    question = request.form['question']
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Eres H.IA, un asistente de estudios con información actual y útil."},
            {"role": "user", "content": question}
        ]
    )
    answer = response.choices[0].message.content
    db.session.add(ChatHistory(question=question, answer=answer))
    user.questions_used += 1
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/reset')
def reset():
    ChatHistory.query.delete()
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/audio', methods=['POST'])
def audio():
    user = User.query.filter_by(session_id=session['user_id']).first()
    if not user.is_premium:
        return "Función premium: suscríbete para generar audios."

    text = request.form['text']
    tts = gTTS(text, lang='es')
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join("static", "audios", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tts.save(filepath)
    return send_file(filepath, as_attachment=True)

# ✅ FRAGMENTO CORREGIDO AQUÍ
@app.route('/imagen', methods=['POST'])
def imagen():
    user = User.query.filter_by(session_id=session['user_id']).first()
    if not user.is_premium and user.images_used >= 2:
        return "Límite gratuito de 2 imágenes alcanzado. Suscríbete para más."

    prompt = request.form['prompt']
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        image_url = response.data[0].url
        user.images_used += 1
        db.session.commit()
        return redirect(image_url)
    except Exception as e:
        return f"Ocurrió un error generando la imagen: {str(e)}", 500

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
    user.is_premium = True
    db.session.commit()
    return "Gracias por suscribirte 🎉 Ahora tienes acceso ilimitado."

if __name__ == '__main__':
    app.run(debug=True)