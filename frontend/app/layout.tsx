import type { Metadata } from "next";
import type { ReactNode } from "react";

import { getPublicEnv, type PublicEnvName } from "@/lib/runtime-env";

import "./globals.css";

export const metadata: Metadata = {
  title: "PostForge",
  description: "PostForge frontend",
};

export const dynamic = "force-dynamic";

const publicEnvNames: PublicEnvName[] = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
  "NEXT_PUBLIC_API_URL",
];

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  const publicEnv = Object.fromEntries(
    publicEnvNames.map((name) => [name, getPublicEnv(name)]),
  );
  const serializedPublicEnv = JSON.stringify(publicEnv).replace(/</g, "\\u003c");

  return (
    <html lang="en">
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `window.__POSTFORGE_PUBLIC_ENV__=${serializedPublicEnv}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
