import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cited Research Workbench",
  description: "Page-cited PDF research with approval gates and an audit trail.",
};

export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
