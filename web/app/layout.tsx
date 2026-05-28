import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MeshyCal",
  description:
    "Your scheduling butler: agent-mediated, privacy-preserving meetings.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
