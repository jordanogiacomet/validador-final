"use client";

import React from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useState } from "react";

import { ApiError, loginOperator } from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

type LoginFieldName = "tenantId" | "username" | "password";

interface LoginScreenProps {
  onAuthenticated: (session: LoginResponse) => void;
}

interface LoginFormState {
  tenantId: string;
  username: string;
  password: string;
}

type LoginFieldErrors = Partial<Record<LoginFieldName, string>>;

const INITIAL_FORM_STATE: LoginFormState = {
  tenantId: "",
  username: "",
  password: "",
};

const INITIAL_ACCESS = {
  tenantId: "default",
  username: "default.operator",
};

const TENANT_ID_PATTERN = /^[A-Za-z0-9._-]+$/;
const USERNAME_PATTERN = /^[A-Za-z0-9._@-]+$/;

function validateLoginForm(values: LoginFormState): LoginFieldErrors {
  const errors: LoginFieldErrors = {};
  const normalizedTenantId = values.tenantId.trim();
  const normalizedUsername = values.username.trim();

  if (!normalizedTenantId) {
    errors.tenantId = "Informe o tenant para entrar no contexto correto.";
  } else if (!TENANT_ID_PATTERN.test(normalizedTenantId)) {
    errors.tenantId = "Use apenas letras, números, ponto, hífen ou underscore.";
  }

  if (!normalizedUsername) {
    errors.username = "Informe o usuário autorizado para este tenant.";
  } else if (!USERNAME_PATTERN.test(normalizedUsername)) {
    errors.username = "Use apenas letras, números, ponto, arroba, hífen ou underscore.";
  }

  if (!values.password.trim()) {
    errors.password = "Informe a senha da operação.";
  }

  return errors;
}

function getLoginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "Credenciais inválidas. Revise usuário e senha.";
    }

    if (error.status === 404) {
      return "Tenant inexistente. Revise o identificador informado.";
    }

    if (error.status === 403) {
      if (error.message === "Operator is not allowed for this tenant") {
        return "Este usuário não pode acessar o tenant informado.";
      }

      if (error.message === "Operator is disabled") {
        return "Este usuário está desabilitado para acesso.";
      }

      return "Acesso negado para o tenant informado.";
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Não foi possível iniciar a sessão operacional.";
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const [formValues, setFormValues] = useState<LoginFormState>(INITIAL_FORM_STATE);
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleFieldChange(field: LoginFieldName) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = event.target.value;
      setFormValues((currentValue) => ({
        ...currentValue,
        [field]: nextValue,
      }));

      setFieldErrors((currentValue) => {
        if (!currentValue[field]) {
          return currentValue;
        }

        const nextErrors = { ...currentValue };
        delete nextErrors[field];
        return nextErrors;
      });

      if (submitError) {
        setSubmitError(null);
      }
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validateLoginForm(formValues);
    setFieldErrors(nextErrors);
    setSubmitError(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setIsSubmitting(true);
    try {
      const session = await loginOperator(formValues);
      setFormValues((currentValue) => ({
        ...currentValue,
        password: "",
      }));
      onAuthenticated(session);
    } catch (error) {
      setSubmitError(getLoginErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <section className="auth-layout">
        <div className="auth-hero">
          <div className="panel-kicker auth-kicker">Plataforma patrimonial</div>
          <h1 className="auth-heading">Acesso seguro para a central operacional multi-tenant.</h1>
          <p className="auth-lead">
            Controle uploads, auditoria e correções com sessão temporária por tenant,
            autenticação hash-based e trilha operacional contínua.
          </p>

          <div className="auth-feature-grid">
            <article className="auth-feature-card">
              <strong>Contexto isolado</strong>
              <p>Cada operador entra no tenant correto antes de abrir jobs, relatórios e exportações.</p>
            </article>
            <article className="auth-feature-card">
              <strong>Credencial temporária</strong>
              <p>O login emite uma chave operacional curta e o frontend reutiliza o header autenticado.</p>
            </article>
            <article className="auth-feature-card">
              <strong>Auditoria rastreável</strong>
              <p>Emissão, expiração e revogação de sessão permanecem alinhadas ao tenant ativo.</p>
            </article>
          </div>

          <div className="auth-trust-row" aria-label="Indicadores de segurança do login">
            <span className="auth-trust-pill">Tenant scoped</span>
            <span className="auth-trust-pill">PBKDF2</span>
            <span className="auth-trust-pill">X-API-Key temporária</span>
          </div>
        </div>

        <section className="panel auth-panel">
          <div className="panel-kicker">Acesso operacional</div>
          <h2 className="panel-title auth-title">Entrar na central</h2>
          <p className="panel-copy auth-copy">
            Informe tenant, usuário e senha para iniciar a sessão do workspace.
          </p>

          <div className="auth-bootstrap-card">
            <div className="auth-bootstrap-head">
              <div>
                <span className="auth-bootstrap-label">Bootstrap local</span>
                <strong>Credenciais iniciais configuradas</strong>
              </div>
              <span className="auth-bootstrap-badge">tenant padrão</span>
            </div>
            <dl className="auth-bootstrap-list">
              <div>
                <dt>Tenant inicial</dt>
                <dd>{INITIAL_ACCESS.tenantId}</dd>
              </div>
              <div>
                <dt>Usuário inicial</dt>
                <dd>{INITIAL_ACCESS.username}</dd>
              </div>
            </dl>
            <p className="auth-bootstrap-note">
              A senha seed fica no tenant default para bootstrap local e deve ser trocada
              na configuração antes de expor o ambiente.
            </p>
          </div>

          <form className="form-grid" noValidate onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="tenant-id">Tenant</label>
              <input
                id="tenant-id"
                name="tenant_id"
                type="text"
                autoComplete="organization"
                inputMode="text"
                value={formValues.tenantId}
                aria-invalid={Boolean(fieldErrors.tenantId)}
                onChange={handleFieldChange("tenantId")}
              />
              {fieldErrors.tenantId ? (
                <p className="inline-error">{fieldErrors.tenantId}</p>
              ) : (
                <small>Use o identificador exato do tenant. Ex.: `default`.</small>
              )}
            </div>

            <div className="field">
              <label htmlFor="username">Usuário</label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                inputMode="email"
                value={formValues.username}
                aria-invalid={Boolean(fieldErrors.username)}
                onChange={handleFieldChange("username")}
              />
              {fieldErrors.username ? (
                <p className="inline-error">{fieldErrors.username}</p>
              ) : (
                <small>O usuário é validado dentro do tenant informado.</small>
              )}
            </div>

            <div className="field">
              <label htmlFor="password">Senha</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={formValues.password}
                aria-invalid={Boolean(fieldErrors.password)}
                onChange={handleFieldChange("password")}
              />
              {fieldErrors.password ? (
                <p className="inline-error">{fieldErrors.password}</p>
              ) : (
                <small>A autenticação usa hash PBKDF2 e chave operacional temporária.</small>
              )}
            </div>

            {submitError ? (
              <p className="inline-error auth-submit-error" role="alert">
                {submitError}
              </p>
            ) : null}

            <button className="cta auth-cta" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Entrando..." : "Entrar"}
            </button>
          </form>
        </section>
      </section>
    </div>
  );
}
