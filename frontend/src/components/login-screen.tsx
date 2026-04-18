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

function validateLoginForm(values: LoginFormState): LoginFieldErrors {
  const errors: LoginFieldErrors = {};

  if (!values.tenantId.trim()) {
    errors.tenantId = "Informe o tenant para entrar no contexto correto.";
  }

  if (!values.username.trim()) {
    errors.username = "Informe o usuário autorizado para este tenant.";
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
      <section className="panel auth-panel">
        <div className="panel-kicker">Acesso operacional</div>
        <h1 className="panel-title auth-title">Entrar</h1>
        <p className="panel-copy auth-copy">Informe tenant, usuário e senha.</p>

        <form className="form-grid" noValidate onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="tenant-id">Tenant</label>
            <input
              id="tenant-id"
              name="tenant_id"
              type="text"
              autoComplete="organization"
              value={formValues.tenantId}
              aria-invalid={Boolean(fieldErrors.tenantId)}
              onChange={handleFieldChange("tenantId")}
            />
            {fieldErrors.tenantId ? (
              <p className="inline-error">{fieldErrors.tenantId}</p>
            ) : (
              <small>Use o identificador exato do tenant.</small>
            )}
          </div>

          <div className="field">
            <label htmlFor="username">Usuário</label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              value={formValues.username}
              aria-invalid={Boolean(fieldErrors.username)}
              onChange={handleFieldChange("username")}
            />
            {fieldErrors.username ? <p className="inline-error">{fieldErrors.username}</p> : null}
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
            {fieldErrors.password ? <p className="inline-error">{fieldErrors.password}</p> : null}
          </div>

          {submitError ? (
            <p className="inline-error auth-submit-error" role="alert">
              {submitError}
            </p>
          ) : null}

          <button className="cta" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Entrando..." : "Entrar"}
          </button>
        </form>
      </section>
    </div>
  );
}
