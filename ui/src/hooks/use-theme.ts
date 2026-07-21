import { useCallback, useEffect, useState } from "react";

type Theme = "dark" | "light";

/** Dark by default; persisted; toggles the `.dark` class shadcn-style. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    typeof localStorage !== "undefined" && localStorage.getItem("theme") === "light"
      ? "light"
      : "dark",
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return { theme, toggle };
}
