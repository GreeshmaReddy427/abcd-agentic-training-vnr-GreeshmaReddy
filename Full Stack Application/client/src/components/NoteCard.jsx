import React from 'react';
import { Card, Button } from 'react-bootstrap';
import './NoteCard.css';

function NoteCard({ note, onEdit, onDelete }) {
    return (
        <Card className="shadow-sm h-100">
            <Card.Body>
                <Card.Title className="fw-bold">{note.title}</Card.Title>
                <Card.Text>{note.content}</Card.Text>
            </Card.Body>
            <Card.Footer className="d-flex justify-content-between align-items-center bg-white">
                <small className="text-muted">{new Date(note.date).toLocaleString()}</small>
                <div>
                    <Button
                        variant="outline-primary"
                        size="sm"
                        className="me-2"
                        onClick={() => onEdit(note)}
                    >
                        Edit
                    </Button>
                    <Button
                        variant="outline-danger"
                        size="sm"
                        onClick={() => onDelete(note.id)}
                    >
                        Delete
                    </Button>
                </div>
            </Card.Footer>
        </Card>
    );
}

export default NoteCard;
