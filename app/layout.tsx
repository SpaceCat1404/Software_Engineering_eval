import "./globals.css";
import Header from "./components/Header";

export const metadata = {
  title: "SE Project Grader",
  description: "AI rubric evaluation for SRS and Test Plan submissions",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Header />
        {children}
      </body>
    </html>
  );
}
