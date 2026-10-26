/** Styles shared by the account pages (/auth, /verify-email, /reset-password, /account/security). */
export const AUTH_CSS = `
        .auth-page {
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: linear-gradient(135deg, #064e3b 0%, #065f46 40%, #047857 70%, #059669 100%);
          padding: 1rem;
          position: relative;
          overflow: hidden;
          font-family: var(--font-geist-sans, sans-serif);
        }
        .auth-page-loading {
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #064e3b;
        }
        .auth-bg-overlay {
          position: absolute;
          inset: 0;
          background:
            radial-gradient(ellipse 80% 60% at 20% 20%, rgba(16,185,129,0.25) 0%, transparent 60%),
            radial-gradient(ellipse 60% 80% at 80% 80%, rgba(5,150,105,0.3) 0%, transparent 60%);
          pointer-events: none;
        }
        .auth-card {
          position: relative;
          z-index: 1;
          background: rgba(255,255,255,0.97);
          backdrop-filter: blur(20px);
          border-radius: 1.5rem;
          box-shadow: 0 25px 60px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.2);
          padding: 2.5rem 2rem;
          width: 100%;
          max-width: 440px;
          animation: authCardIn 0.4s cubic-bezier(.22,1,.36,1);
        }
        @keyframes authCardIn {
          from { opacity:0; transform:translateY(24px) scale(0.97); }
          to   { opacity:1; transform:translateY(0) scale(1); }
        }
        .auth-logo {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          margin-bottom: 1.75rem;
        }
        .auth-logo-icon {
          font-size: 2.5rem;
          line-height: 1;
          filter: drop-shadow(0 2px 4px rgba(0,0,0,0.2));
        }
        .auth-logo-title {
          font-size: 1.5rem;
          font-weight: 800;
          color: #064e3b;
          margin: 0;
          letter-spacing: -0.02em;
        }
        .auth-logo-sub {
          font-size: 0.72rem;
          color: #6b7280;
          margin: 0;
          font-weight: 500;
        }
        .auth-tabs {
          display: flex;
          background: #f3f4f6;
          border-radius: 0.75rem;
          padding: 0.25rem;
          margin-bottom: 1.5rem;
          gap: 0.25rem;
        }
        .auth-tab {
          flex: 1;
          padding: 0.6rem 1rem;
          border: none;
          background: transparent;
          border-radius: 0.5rem;
          font-size: 0.875rem;
          font-weight: 600;
          color: #6b7280;
          cursor: pointer;
          transition: all 0.2s;
        }
        .auth-tab--active {
          background: white;
          color: #064e3b;
          box-shadow: 0 1px 4px rgba(0,0,0,0.12);
        }
        .auth-back-row {
          margin-bottom: 1.25rem;
        }
        .auth-back-btn {
          background: none;
          border: none;
          color: #059669;
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
          padding: 0;
          margin-bottom: 0.5rem;
        }
        .auth-back-btn:hover { text-decoration: underline; }
        .auth-form-title {
          font-size: 1.25rem;
          font-weight: 700;
          color: #111827;
          margin: 0;
        }
        .auth-form {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }
        .auth-field {
          display: flex;
          flex-direction: column;
          gap: 0.35rem;
        }
        .auth-hint { font-size: 0.8rem; color: #4b5563; margin: 0.25rem 0 0; line-height: 1.5; }
  .auth-label {
          font-size: 0.82rem;
          font-weight: 600;
          color: #374151;
        }
        .auth-required { color: #ef4444; }
        .auth-input {
          padding: 0.65rem 0.85rem;
          border: 1.5px solid #d1d5db;
          border-radius: 0.65rem;
          font-size: 0.9rem;
          color: #111827;
          background: #f9fafb;
          transition: border-color 0.2s, box-shadow 0.2s;
          outline: none;
          width: 100%;
          box-sizing: border-box;
        }
        .auth-input:focus {
          border-color: #059669;
          box-shadow: 0 0 0 3px rgba(5,150,105,0.15);
          background: white;
        }
        .auth-input--password { padding-right: 2.75rem; }
        .auth-password-wrap {
          position: relative;
        }
        .auth-show-password {
          position: absolute;
          right: 0.6rem;
          top: 50%;
          transform: translateY(-50%);
          background: none;
          border: none;
          cursor: pointer;
          font-size: 1rem;
          line-height: 1;
          padding: 0.25rem;
          color: #6b7280;
        }
        .auth-forgot-link {
          align-self: flex-end;
          background: none;
          border: none;
          color: #059669;
          font-size: 0.8rem;
          font-weight: 600;
          cursor: pointer;
          padding: 0;
          margin-top: 0.2rem;
        }
        .auth-forgot-link:hover { text-decoration: underline; }
        .auth-alert {
          padding: 0.7rem 0.9rem;
          border-radius: 0.65rem;
          font-size: 0.85rem;
          font-weight: 500;
        }
        .auth-alert--error {
          background: #fef2f2;
          color: #991b1b;
          border: 1px solid #fecaca;
        }
        .auth-alert--success {
          background: #f0fdf4;
          color: #166534;
          border: 1px solid #bbf7d0;
        }
        .auth-submit {
          margin-top: 0.5rem;
          padding: 0.8rem 1rem;
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
          color: white;
          border: none;
          border-radius: 0.75rem;
          font-size: 0.95rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
          box-shadow: 0 4px 12px rgba(5,150,105,0.35);
          min-height: 48px;
        }
        .auth-submit:hover:not(:disabled) {
          background: linear-gradient(135deg, #047857 0%, #065f46 100%);
          box-shadow: 0 6px 16px rgba(5,150,105,0.45);
          transform: translateY(-1px);
        }
        .auth-submit:active:not(:disabled) { transform: translateY(0); }
        .auth-submit:disabled { opacity: 0.65; cursor: not-allowed; transform: none; }
        .auth-btn-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
        }
        .auth-terms {
          font-size: 0.75rem;
          color: #9ca3af;
          text-align: center;
          margin: 0;
          line-height: 1.5;
        }
        .auth-spinner {
          width: 2.5rem;
          height: 2.5rem;
          border: 3px solid rgba(255,255,255,0.3);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
        }
        .auth-spinner-sm {
          width: 1rem;
          height: 1rem;
          border: 2px solid rgba(255,255,255,0.4);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
          display: inline-block;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
`;
