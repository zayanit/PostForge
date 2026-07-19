import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request: { headers: request.headers } });
  if (!supabaseUrl || !supabaseAnonKey) {
    if (request.nextUrl.pathname === "/" || request.nextUrl.pathname.startsWith("/account")) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    return response;
  }

  const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: Array<{ name: string; value: string; options?: any }>) {
        cookiesToSet.forEach(({ name, value, options }) => {
          response.cookies.set({ name, value, ...options });
        });
      },
    },
  });

  const { data } = await supabase.auth.getUser();
  const isProtected = request.nextUrl.pathname === "/" || request.nextUrl.pathname.startsWith("/account");

  if (!data.user && isProtected) {
    const redirectUrl = new URL("/login", request.url);
    const redirectResponse = NextResponse.redirect(redirectUrl);
    // Carry over any cookie mutations (refreshed/cleared auth cookies) that
    // getUser() applied to `response` via setAll — a fresh redirect response
    // otherwise loses them, leaving stale cookies in the browser.
    response.cookies.getAll().forEach((cookie) => {
      redirectResponse.cookies.set(cookie);
    });
    return redirectResponse;
  }

  return response;
}

export const config = {
  matcher: ["/", "/account", "/account/:path*"],
};
