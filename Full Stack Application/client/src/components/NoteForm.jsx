import React, { useState, useEffect } from 'react';
import { Form, Button, Card } from 'react-bootstrap';

function NoteForm({ noteToEdit, onSubmit, onCancel }) {
    const [title, setTitle] = useState('');
    const [content, setContent] = useState('');

    useEffect(() => {
        if (noteToEdit) {
            setTitle(noteToEdit.title);
            setContent(noteToEdit.content);
        } else {
            setTitle('');
            setContent('');
        }
    }, [noteToEdit]);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!title.trim() || !content.trim()) return;
        const note = noteToEdit
            ? { ...noteToEdit, title, content }
            : { title, content };
        onSubmit(note);
        setTitle('');
        setContent('');
    };

    return (
        <Card>
            <Card.Body>
                <Form onSubmit={handleSubmit}>
                    <Form.Group className="mb-3" controlId="noteTitle">
                        <Form.Label>Title</Form.Label>
                        <Form.Control
                            type="text"
                            placeholder="Enter note title"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            required
                        />
                    </Form.Group>
                    <Form.Group className="mb-3" controlId="noteContent">
                        <Form.Label>Content</Form.Label>
                        <Form.Control
                            as="textarea"
                            rows={4}
                            placeholder="Enter note content"
                            value={content}
                            onChange={(e) => setContent(e.target.value)}
                            required
                        />
                    </Form.Group>
                    <div className="d-flex justify-content-end">
                        <Button variant="secondary" className="me-2" onClick={onCancel}>
                            Cancel
                        </Button>
                        <Button variant="primary" type="submit">
                            {noteToEdit ? 'Update Note' : 'Add Note'}
                        </Button>
                    </div>
                </Form>
            </Card.Body>
        </Card>
    );
}

export default NoteForm;