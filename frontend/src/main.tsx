import { createRoot } from 'react-dom/client'
import { IconContext } from '@phosphor-icons/react'
import App from './App'
import '@fontsource/geist/400.css'
import '@fontsource/geist/500.css'
import '@fontsource/geist/600.css'
import '@fontsource/geist-mono/400.css'
import '@fontsource/geist-mono/500.css'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <IconContext.Provider value={{ weight: 'bold' }}><App /></IconContext.Provider>,
)
