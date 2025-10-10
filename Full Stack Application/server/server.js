const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');

const app = express();
const PORT = 5000;

// Middleware
app.use(cors());
app.use(express.json());

// MongoDB Connection
mongoose.connect('mongodb://localhost:27017/notesDB')
    .then(() => console.log('Connected to MongoDB'))
    .catch(err => console.error('MongoDB connection error:', err));

// Note Schema
const noteSchema = new mongoose.Schema({
    title: String,
    content: String,
    date: {
        type: Date,
        default: Date.now
    }
});

const Note = mongoose.model('Note', noteSchema);

// Routes
app.get('/api/notes', async (req, res) => {
    try {
        const notes = await Note.find().sort({ date: -1 });
        res.json(notes);
    } catch (error) {
        res.status(500).json({ message: error.message });
    }
});

app.post('/api/notes', async (req, res) => {
    try {
        const newNote = new Note(req.body);
        const savedNote = await newNote.save();
        res.status(201).json(savedNote);
    } catch (error) {
        res.status(400).json({ message: error.message });
    }
});

app.put('/api/notes/:id', async (req, res) => {
    try {
        const updatedNote = await Note.findByIdAndUpdate(
            req.params.id,
            req.body,
            { new: true }
        );
        res.json(updatedNote);
    } catch (error) {
        res.status(400).json({ message: error.message });
    }
});

app.delete('/api/notes/:id', async (req, res) => {
    try {
        await Note.findByIdAndDelete(req.params.id);
        res.json({ message: 'Note deleted successfully' });
    } catch (error) {
        res.status(500).json({ message: error.message });
    }
});

app.listen(PORT, () => {
    console.log(`Server is running on http://localhost:${PORT}`);
});