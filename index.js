const express = require('express');
const cors = require('cors');
const app = express();

// Permitir cualquier origen (CORS)
app.use(cors());

// Ruta de prueba
app.get('/', (req, res) => {
  res.json({ message: 'Node API OK' });
});

// Mismo endpoint que tenías en FastAPI
app.post('/transcribe', express.json(), (req, res) => {
  // No importa el body, devolvemos siempre esto
  res.json({ transcription: 'Simulación OK desde Node' });
});

const port = process.env.PORT || 8000;
app.listen(port, () => {
  console.log(`🚀 Node API corriendo en puerto ${port}`);
});
