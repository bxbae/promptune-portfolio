import "./globals.css";
import ShellSwitch from "@/components/ShellSwitch";

export const metadata = { title: "PrompTune", description: "프롬프트 개선 코파일럿" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <ShellSwitch>{children}</ShellSwitch>
      </body>
    </html>
  );
}
