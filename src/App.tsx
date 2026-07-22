/**
 * 설치 확인용 임시 화면.
 * Router / Layout / Theme 은 Phase 0 에서 이 파일을 대체합니다.
 */
export default function App() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <span className="mx-auto flex size-12 items-center justify-center rounded-xl bg-gradient-to-br from-[#0F73D8] to-[#38D0B8] text-lg font-extrabold text-white">
          A
        </span>
        <h1 className="mt-5 text-2xl font-extrabold tracking-tight text-slate-800">
          AXit
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          AI 문서 통합 플랫폼
          <br />
          개발 환경 설정이 완료되었습니다.
        </p>
        <ul className="mt-6 space-y-1.5 text-left text-[13px] text-slate-500">
          {[
            'React 19 + TypeScript (strict)',
            'Vite + @/* 경로 alias',
            'Tailwind CSS v4',
            'React Router · TanStack Query · Axios',
            'Framer Motion · lucide-react · Recharts',
          ].map((item) => (
            <li key={item} className="flex items-center gap-2">
              <span className="size-1.5 shrink-0 rounded-full bg-[#38D0B8]" />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
