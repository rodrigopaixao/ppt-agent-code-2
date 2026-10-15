import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deck Studio",
  description: "Create editable presentations from an approved template",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
