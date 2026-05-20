import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';

const inter = Inter({ subsets: ['latin'], variable: '--font-sans' });

export const metadata: Metadata = {
  title: 'Agentic Exchange | Somnia',
  description: 'Autonomous AI trading agents on Somnia blockchain',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} font-sans bg-[#080808] text-white antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
