import { useCallback, useEffect, useState } from "react";

type Theme = "dark" | "light";
const THEME_STORAGE_VERSION = "cream-light-v1";

/** Light by default; persisted; toggles the `.dark` class shadcn-style. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    typeof localStorage !== "undefined"
      && localStorage.getItem("theme-version") === THEME_STORAGE_VERSION
      && localStorage.getItem("theme") === "dark"
      ? "dark"
      : "light",
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme", theme);
    localStorage.setItem("theme-version", THEME_STORAGE_VERSION);
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return { theme, toggle };
}
