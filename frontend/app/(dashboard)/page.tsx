import Link from "next/link";

export default function HomePage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-2 text-sm text-gray-600">You are signed in.</p>
      <Link className="mt-6 inline-block rounded-md border px-3 py-2 text-sm" href="/account">
        Account settings
      </Link>
    </section>
  );
}
