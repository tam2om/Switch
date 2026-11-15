import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Aruba Network Manager",
  description: "Internal management of Aruba AOS-Switch fleets",
  robots: { index: false, follow: false },
};

// Applies the saved theme before first paint to avoid a flash of the wrong theme.
const themeScript = `try{var t=localStorage.getItem("anm.theme");var c=document.documentElement.classList;if(t==="light"){c.add("light")}else{c.add("dark")}}catch(e){document.documentElement.classList.add("dark")}`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Set by middleware.ts; reading it also makes every page render per request so each response gets a fresh nonce.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
