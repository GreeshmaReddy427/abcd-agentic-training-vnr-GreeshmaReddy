import React, { useState, useEffect } from 'react';
import NoteCard from './NoteCard';
import NoteForm from './NoteForm';
import { Container, Row, Col, Button } from 'react-bootstrap';
import './Home.css';

function Home() {
    const [notes, setNotes] = useState([]);
    const [editingNote, setEditingNote] = useState(null);
    const [showForm, setShowForm] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        fetchNotes();
    }, []);

    const fetchNotes = async () => {
        try {
            const response = await fetch('http://localhost:5000/api/notes');
            if (!response.ok) {
                throw new Error('Failed to fetch notes');
            }
            const data = await response.json();
            setNotes(data);
            setLoading(false);
        } catch (error) {
            console.error('Error fetching notes:', error);
            setError(error.message);
            setLoading(false);
        }
    };

    const handleAddNote = async (note) => {
        try {
            const response = await fetch('http://localhost:5000/api/notes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(note),
            });
            if (!response.ok) {
                throw new Error('Failed to add note');
            }
            const savedNote = await response.json();
            setNotes(prevNotes => [savedNote, ...prevNotes]);
            setShowForm(false);
        } catch (error) {
            console.error('Error adding note:', error);
            setError(error.message);
        }
    };

    const handleEditNote = async (updatedNote) => {
        try {
            const response = await fetch(`http://localhost:5000/api/notes/${updatedNote._id}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updatedNote),
            });
            if (!response.ok) {
                throw new Error('Failed to update note');
            }
            const savedNote = await response.json();
            setNotes(prevNotes => 
                prevNotes.map(note => note._id === savedNote._id ? savedNote : note)
            );
            setEditingNote(null);
            setShowForm(false);
        } catch (error) {
            console.error('Error updating note:', error);
            setError(error.message);
        }
    };

    const handleDeleteNote = async (id) => {
        try {
            const response = await fetch(`http://localhost:5000/api/notes/${id}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                throw new Error('Failed to delete note');
            }
            setNotes(prevNotes => prevNotes.filter(note => note._id !== id));
        } catch (error) {
            console.error('Error deleting note:', error);
            setError(error.message);
        }
    };

    const handleEditClick = (note) => {
        setEditingNote(note);
        setShowForm(true);
    };

    const handleCancel = () => {
        setEditingNote(null);
        setShowForm(false);
    };

    if (loading) {
        return (
            <Container className="text-center py-5">
                <div className="spinner-border text-primary" role="status">
                    <span className="visually-hidden">Loading...</span>
                </div>
            </Container>
        );
    }

    if (error) {
        return (
            <Container className="text-center py-5">
                <div className="alert alert-danger" role="alert">
                    {error}
                </div>
            </Container>
        );
    }

    return (
        <Container className="py-5">
            <div className="welcome-section">
                <h1 className="welcome-title">My Notes</h1>
                <Button 
                    variant="success" 
                    size="lg"
                    className="add-note-btn"
                    onClick={() => {
                        setEditingNote(null);
                        setShowForm(true);
                    }}
                >
                    <i className="bi bi-plus-lg me-2"></i>
                    Create New Note
                </Button>
            </div>

            {showForm && (
                <Row className="mb-4">
                    <Col md={8} lg={6} className="mx-auto">
                        <NoteForm
                            noteToEdit={editingNote}
                            onSubmit={editingNote ? handleEditNote : handleAddNote}
                            onCancel={handleCancel}
                        />
                    </Col>
                </Row>
            )}

            <Row xs={1} md={2} lg={3} className="notes-grid">
                {notes.length === 0 && !showForm ? (
                    <Col xs={12}>
                        <div className="empty-notes-placeholder">
                            <h3 className="text-secondary">No Notes Yet</h3>
                            <p className="text-muted">
                                Click the "Create New Note" button to add your first note!
                            </p>
                        </div>
                    </Col>
                ) : (
                    notes.map(note => (
                        <Col key={note._id}>
                            <NoteCard
                                note={note}
                                onEdit={handleEditClick}
                                onDelete={handleDeleteNote}
                            />
                        </Col>
                    ))
                )}
            </Row>
        </Container>
    );
}

export default Home;