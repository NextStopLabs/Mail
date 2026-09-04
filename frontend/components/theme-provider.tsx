"use client"
import { createContext, useContext, useEffect, useState } from "react"

type Theme = "light"|"dark"|"system"
const Ctx = createContext<{theme:Theme, setTheme:(t:Theme)=>void}>({theme:"system", setTheme:()=>{}})

export function ThemeProvider({children}:{children:React.ReactNode}) {
  const [theme, setTheme] = useState<Theme>("system")
  useEffect(()=>{
    const saved = (localStorage.getItem("theme") as Theme) || "system"
    setTheme(saved)
  },[])
  useEffect(()=>{
    localStorage.setItem("theme", theme)
    const root = document.documentElement
    root.classList.remove("light","dark")
    if (theme === "system") {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
      root.classList.add(prefersDark ? "dark" : "light")
    } else {
      root.classList.add(theme)
    }
  },[theme])
  return <Ctx.Provider value={{theme, setTheme}}>{children}</Ctx.Provider>
}
export const useTheme = ()=> useContext(Ctx)
