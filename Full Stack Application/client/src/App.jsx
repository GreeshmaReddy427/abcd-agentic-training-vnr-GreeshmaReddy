import React from 'react';
import RootLayout from './components/RootLayout';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import Home from './components/Home';
import NoteCard from './components/NoteCard';
import NoteForm from './components/NoteForm';
import './App.css';

function App() {
  const router = createBrowserRouter([
    {
      path:"/",
      element:<RootLayout/>,
      children:[
        {
          path:"",
          element:<Home/>
        },
        {
          path:"card",
          element:<NoteCard/>
        },
        {
          path:"form",
          element:<NoteForm/>
        }
      ]
    }
  ])
  return (
    <div>
      <RouterProvider router={router}/>
    </div>
  )
}

export default App;