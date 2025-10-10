import React from 'react';
import Header from './Header';
import { Outlet } from 'react-router-dom';
import '../App.css'; 

function RootLayout() {
    return (
        <>
            <Header />
            <main>
                <Outlet />
            </main>
        </>
    );
}

export default RootLayout;