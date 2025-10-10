import { Navbar, Container } from 'react-bootstrap';

function Header() {
    return (
        <Navbar bg="primary" variant="dark" expand="lg">
            <Container>
                <Navbar.Brand href="/" className="fw-bold">
                    Notes App
                </Navbar.Brand>
            </Container>
        </Navbar>
    );
}

export default Header;