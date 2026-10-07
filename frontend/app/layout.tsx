import type { Metadata } from "next";
import "./styles.css";
export const metadata: Metadata = { title: "Fieldnote | Geopolitical Intelligence", description: "Local-first geopolitical OSINT intelligence dashboard" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
