"use client";

import React from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useState } from "react";

import {
  ApiError,
  completePasswordSetup,
  createInitialAdmin,
  getInitialSetupState,
  loginOperator,
} from "@/lib/api";
import type { InitialSetupState, LoginResponse } from "@/lib/types";

type LoginFieldName = "tenantId" | "username" | "password";
type SetupFieldName = "username" | "password" | "setupToken";
type PasswordSetupFieldName = "newPassword";

interface LoginScreenProps {
  onAuthenticated: (session: LoginResponse) => void;
}

interface LoginFormState {
  tenantId: string;
  username: string;
  password: string;
}

interface SetupFormState {
  username: string;
  password: string;
  setupToken: string;
}

interface PasswordSetupFormState {
  newPassword: string;
}

type LoginFieldErrors = Partial<Record<LoginFieldName, string>>;
type SetupFieldErrors = Partial<Record<SetupFieldName, string>>;
type PasswordSetupFieldErrors = Partial<Record<PasswordSetupFieldName, string>>;

const INITIAL_FORM_STATE: LoginFormState = {
  tenantId: "",
  username: "",
  password: "",
};

const INITIAL_SETUP_FORM_STATE: SetupFormState = {
  username: "",
  password: "",
  setupToken: "",
};

const INITIAL_PASSWORD_SETUP_FORM_STATE: PasswordSetupFormState = {
  newPassword: "",
};

const INITIAL_ACCESS = {
  tenantId: "default",
  username: "default.operator",
};

const TENANT_ID_PATTERN = /^[A-Za-z0-9._-]+$/;
const USERNAME_PATTERN = /^[A-Za-z0-9._@-]+$/;

function shouldShowDevLoginHints(): boolean {
  return process.env.NEXT_PUBLIC_SHOW_DEV_LOGIN_HINTS === "true";
}

function appendSupportCode(message: string, error: unknown): string {
  if (error instanceof ApiError && error.requestId) {
    return `${message} Código de suporte: ${error.requestId}.`;
  }

  return message;
}

function validateLoginForm(values: LoginFormState): LoginFieldErrors {
  const errors: LoginFieldErrors = {};
  const normalizedTenantId = values.tenantId.trim();
  const normalizedUsername = values.username.trim();

  if (!normalizedTenantId) {
    errors.tenantId = "Informe o código da empresa.";
  } else if (!TENANT_ID_PATTERN.test(normalizedTenantId)) {
    errors.tenantId = "Use apenas letras, números, ponto, hífen ou underscore.";
  }

  if (!normalizedUsername) {
    errors.username = "Informe o usuário autorizado para essa empresa.";
  } else if (!USERNAME_PATTERN.test(normalizedUsername)) {
    errors.username = "Use apenas letras, números, ponto, arroba, hífen ou underscore.";
  }

  if (!values.password.trim()) {
    errors.password = "Informe a senha para continuar.";
  }

  return errors;
}

function validateSetupForm(
  values: SetupFormState,
  setupState: InitialSetupState | null,
): SetupFieldErrors {
  const errors: SetupFieldErrors = {};
  const normalizedUsername = values.username.trim();

  if (!normalizedUsername) {
    errors.username = "Informe o usuário administrador.";
  } else if (!USERNAME_PATTERN.test(normalizedUsername)) {
    errors.username = "Use apenas letras, números, ponto, arroba, hífen ou underscore.";
  }

  if (!values.password.trim()) {
    errors.password = "Informe a senha inicial.";
  }

  if (setupState?.requires_setup_token && !values.setupToken.trim()) {
    errors.setupToken = "Informe o token de setup.";
  }

  return errors;
}

function getLoginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return appendSupportCode("Credenciais inválidas. Revise usuário e senha.", error);
    }

    if (error.status === 404) {
      return appendSupportCode("Empresa inexistente. Revise o código informado.", error);
    }

    if (error.status === 403) {
      if (error.detail === "Operator is not allowed for this tenant") {
        return appendSupportCode("Este usuário não pode acessar a empresa informada.", error);
      }

      if (error.detail === "Operator is disabled") {
        return appendSupportCode("Este usuário está desabilitado.", error);
      }

      return appendSupportCode("Acesso negado para a empresa informada.", error);
    }

    return error.message;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Não foi possível iniciar a sessão operacional.";
}

function getSetupErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return appendSupportCode("Token de setup inválido.", error);
    }

    if (error.status === 409) {
      return appendSupportCode("O primeiro acesso já foi configurado.", error);
    }

    if (error.status === 503) {
      return appendSupportCode(
        "Configure o storage persistente antes de criar o administrador inicial.",
        error,
      );
    }

    return error.message;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Não foi possível criar o administrador inicial.";
}

function validatePasswordSetupForm(
  values: PasswordSetupFormState,
): PasswordSetupFieldErrors {
  const errors: PasswordSetupFieldErrors = {};
  if (!values.newPassword.trim()) {
    errors.newPassword = "Informe a nova senha para concluir o acesso.";
  }
  return errors;
}

function getPasswordSetupErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return appendSupportCode("A sessão temporária expirou. Entre novamente.", error);
    }

    if (error.status === 403) {
      return appendSupportCode(
        "Esta sessão exige a troca imediata de senha antes do acesso.",
        error,
      );
    }

    if (error.status === 409) {
      return appendSupportCode(
        "A troca obrigatória de senha já foi concluída para este usuário.",
        error,
      );
    }

    return error.message;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Não foi possível concluir a troca obrigatória de senha.";
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const showDevLoginHints = shouldShowDevLoginHints();
  const [formValues, setFormValues] = useState<LoginFormState>(INITIAL_FORM_STATE);
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [setupState, setSetupState] = useState<InitialSetupState | null>(null);
  const [setupValues, setSetupValues] = useState<SetupFormState>(
    INITIAL_SETUP_FORM_STATE,
  );
  const [setupFieldErrors, setSetupFieldErrors] = useState<SetupFieldErrors>({});
  const [setupError, setSetupError] = useState<string | null>(null);
  const [setupSuccess, setSetupSuccess] = useState<string | null>(null);
  const [isSetupSubmitting, setIsSetupSubmitting] = useState(false);
  const [pendingPasswordSetupSession, setPendingPasswordSetupSession] =
    useState<LoginResponse | null>(null);
  const [passwordSetupValues, setPasswordSetupValues] = useState<PasswordSetupFormState>(
    INITIAL_PASSWORD_SETUP_FORM_STATE,
  );
  const [passwordSetupFieldErrors, setPasswordSetupFieldErrors] =
    useState<PasswordSetupFieldErrors>({});
  const [passwordSetupError, setPasswordSetupError] = useState<string | null>(null);
  const [passwordSetupSuccess, setPasswordSetupSuccess] = useState<string | null>(null);
  const [isPasswordSetupSubmitting, setIsPasswordSetupSubmitting] = useState(false);

  useEffect(() => {
    let isMounted = true;

    getInitialSetupState()
      .then((state) => {
        if (isMounted) {
          setSetupState(state);
        }
      })
      .catch(() => {
        if (isMounted) {
          setSetupState(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

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

  function handleSetupFieldChange(field: SetupFieldName) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = event.target.value;
      setSetupValues((currentValue) => ({
        ...currentValue,
        [field]: nextValue,
      }));

      setSetupFieldErrors((currentValue) => {
        if (!currentValue[field]) {
          return currentValue;
        }

        const nextErrors = { ...currentValue };
        delete nextErrors[field];
        return nextErrors;
      });

      if (setupError) {
        setSetupError(null);
      }
    };
  }

  function handlePasswordSetupFieldChange(field: PasswordSetupFieldName) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = event.target.value;
      setPasswordSetupValues((currentValue) => ({
        ...currentValue,
        [field]: nextValue,
      }));

      setPasswordSetupFieldErrors((currentValue) => {
        if (!currentValue[field]) {
          return currentValue;
        }

        const nextErrors = { ...currentValue };
        delete nextErrors[field];
        return nextErrors;
      });

      if (passwordSetupError) {
        setPasswordSetupError(null);
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
      if (session.must_change_password) {
        setPendingPasswordSetupSession(session);
        setPasswordSetupValues(INITIAL_PASSWORD_SETUP_FORM_STATE);
        setPasswordSetupFieldErrors({});
        setPasswordSetupError(null);
        setPasswordSetupSuccess(null);
        return;
      }
      setPendingPasswordSetupSession(null);
      setPasswordSetupSuccess(null);
      onAuthenticated(session);
    } catch (error) {
      setSubmitError(getLoginErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSetupSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validateSetupForm(setupValues, setupState);
    setSetupFieldErrors(nextErrors);
    setSetupError(null);
    setSetupSuccess(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setIsSetupSubmitting(true);
    try {
      const operator = await createInitialAdmin({
        username: setupValues.username,
        password: setupValues.password,
        setupToken: setupValues.setupToken,
      });
      setSetupValues(INITIAL_SETUP_FORM_STATE);
      setSetupState((currentValue) =>
        currentValue
          ? {
              ...currentValue,
              available: false,
            }
          : currentValue,
      );
      setSetupSuccess("Administrador inicial criado. Entre com o usuário criado.");
      setFormValues({
        tenantId: operator.tenant_id,
        username: operator.username,
        password: "",
      });
    } catch (error) {
      setSetupError(getSetupErrorMessage(error));
    } finally {
      setIsSetupSubmitting(false);
    }
  }

  async function handlePasswordSetupSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validatePasswordSetupForm(passwordSetupValues);
    setPasswordSetupFieldErrors(nextErrors);
    setPasswordSetupError(null);

    if (Object.keys(nextErrors).length > 0 || !pendingPasswordSetupSession) {
      return;
    }

    setIsPasswordSetupSubmitting(true);
    try {
      await completePasswordSetup({
        apiKey: pendingPasswordSetupSession.x_api_key,
        newPassword: passwordSetupValues.newPassword,
      });
      setPendingPasswordSetupSession(null);
      setPasswordSetupValues(INITIAL_PASSWORD_SETUP_FORM_STATE);
      setPasswordSetupSuccess(
        "Senha temporária atualizada. Entre novamente com a nova senha.",
      );
      setFormValues((currentValue) => ({
        ...currentValue,
        password: "",
      }));
    } catch (error) {
      setPasswordSetupError(getPasswordSetupErrorMessage(error));
    } finally {
      setIsPasswordSetupSubmitting(false);
    }
  }

  function handlePasswordSetupCancel() {
    setPendingPasswordSetupSession(null);
    setPasswordSetupValues(INITIAL_PASSWORD_SETUP_FORM_STATE);
    setPasswordSetupFieldErrors({});
    setPasswordSetupError(null);
  }

  return (
    <div className="auth-shell">
      <section className="auth-layout">
        <div className="auth-hero">
          <div className="panel-kicker auth-kicker">Validação patrimonial</div>
          <h1 className="auth-heading">Entre e siga um fluxo simples de conferência patrimonial.</h1>
          <p className="auth-lead">
            A tela foi organizada para três passos diretos: entrar, enviar a planilha e revisar o resultado.
          </p>

          <div className="auth-feature-grid">
            <article className="auth-feature-card">
              <strong>1. Entrar</strong>
              <p>Informe empresa, usuário e senha para abrir sua área de trabalho.</p>
            </article>
            <article className="auth-feature-card">
              <strong>2. Enviar a planilha</strong>
              <p>Escolha o CSV e o tipo de conferência. O processamento começa logo em seguida.</p>
            </article>
            <article className="auth-feature-card">
              <strong>3. Corrigir e baixar</strong>
              <p>Revise as pendências, faça os ajustes necessários e exporte os arquivos finais.</p>
            </article>
          </div>

          <div className="auth-trust-row" aria-label="Atalhos do fluxo inicial">
            <span className="auth-trust-pill">Sem telas extras</span>
            <span className="auth-trust-pill">Busca simples</span>
            <span className="auth-trust-pill">Exportação direta</span>
          </div>
        </div>

        <section className="panel auth-panel">
          <div className="panel-kicker">Acesso</div>
          <h2 className="panel-title auth-title">Abra sua área de trabalho</h2>
          <p className="panel-copy auth-copy">
            Informe empresa, usuário e senha. Depois disso você já poderá enviar a planilha.
          </p>

          {setupState?.available ? (
            <div className="auth-bootstrap-card auth-setup-card">
              <div className="auth-bootstrap-head">
                <div>
                  <span className="auth-bootstrap-label">Primeiro acesso</span>
                  <strong>Criar administrador inicial</strong>
                </div>
                <span className="auth-bootstrap-badge">uso único</span>
              </div>
              <form className="form-grid auth-setup-form" noValidate onSubmit={handleSetupSubmit}>
                <div className="field">
                  <label htmlFor="setup-username">Usuário administrador</label>
                  <input
                    id="setup-username"
                    name="setup_username"
                    type="text"
                    autoComplete="username"
                    inputMode="email"
                    value={setupValues.username}
                    aria-invalid={Boolean(setupFieldErrors.username)}
                    onChange={handleSetupFieldChange("username")}
                  />
                  {setupFieldErrors.username ? (
                    <p className="inline-error">{setupFieldErrors.username}</p>
                  ) : (
                    <small>Esse usuário será vinculado à empresa inicial.</small>
                  )}
                </div>

                <div className="field">
                  <label htmlFor="setup-password">Senha inicial</label>
                  <input
                    id="setup-password"
                    name="setup_password"
                    type="password"
                    autoComplete="new-password"
                    value={setupValues.password}
                    aria-invalid={Boolean(setupFieldErrors.password)}
                    onChange={handleSetupFieldChange("password")}
                  />
                  {setupFieldErrors.password ? (
                    <p className="inline-error">{setupFieldErrors.password}</p>
                  ) : (
                    <small>A senha não é exibida nem armazenada em texto puro.</small>
                  )}
                </div>

                {setupState.requires_setup_token ? (
                  <div className="field">
                    <label htmlFor="setup-token">Token de setup</label>
                    <input
                      id="setup-token"
                      name="setup_token"
                      type="password"
                      autoComplete="one-time-code"
                      value={setupValues.setupToken}
                      aria-invalid={Boolean(setupFieldErrors.setupToken)}
                      onChange={handleSetupFieldChange("setupToken")}
                    />
                    {setupFieldErrors.setupToken ? (
                      <p className="inline-error">{setupFieldErrors.setupToken}</p>
                    ) : (
                      <small>Use o token configurado para este ambiente.</small>
                    )}
                  </div>
                ) : null}

                {setupError ? (
                  <p className="inline-error auth-submit-error" role="alert">
                    {setupError}
                  </p>
                ) : null}

                <button className="cta auth-cta" type="submit" disabled={isSetupSubmitting}>
                  {isSetupSubmitting ? "Criando..." : "Criar administrador"}
                </button>
              </form>
            </div>
          ) : null}

          {setupSuccess ? (
            <div className="auth-bootstrap-card auth-setup-success" role="status">
              <div className="auth-bootstrap-head">
                <div>
                  <span className="auth-bootstrap-label">Primeiro acesso</span>
                  <strong>{setupSuccess}</strong>
                </div>
                <span className="auth-bootstrap-badge">concluído</span>
              </div>
            </div>
          ) : null}

          {showDevLoginHints ? (
            <div className="auth-bootstrap-card">
              <div className="auth-bootstrap-head">
                <div>
                  <span className="auth-bootstrap-label">Ambiente local</span>
                  <strong>Dados iniciais de desenvolvimento</strong>
                </div>
                <span className="auth-bootstrap-badge">somente dev</span>
              </div>
              <dl className="auth-bootstrap-list">
                <div>
                  <dt>Empresa inicial</dt>
                  <dd>{INITIAL_ACCESS.tenantId}</dd>
                </div>
                <div>
                  <dt>Usuário inicial</dt>
                  <dd>{INITIAL_ACCESS.username}</dd>
                </div>
              </dl>
              <p className="auth-bootstrap-note">
                Esta dica só aparece quando NEXT_PUBLIC_SHOW_DEV_LOGIN_HINTS=true.
              </p>
            </div>
          ) : null}

          {passwordSetupSuccess ? (
            <div className="auth-bootstrap-card auth-setup-success" role="status">
              <div className="auth-bootstrap-head">
                <div>
                  <span className="auth-bootstrap-label">Senha temporária</span>
                  <strong>{passwordSetupSuccess}</strong>
                </div>
                <span className="auth-bootstrap-badge">concluído</span>
              </div>
            </div>
          ) : null}

          {pendingPasswordSetupSession ? (
            <div className="auth-bootstrap-card auth-setup-card">
              <div className="auth-bootstrap-head">
                <div>
                  <span className="auth-bootstrap-label">Troca obrigatória</span>
                  <strong>Defina a nova senha antes de acessar a área operacional</strong>
                </div>
                <span className="auth-bootstrap-badge">primeiro login</span>
              </div>
              <form className="form-grid auth-setup-form" noValidate onSubmit={handlePasswordSetupSubmit}>
                <div className="field">
                  <label htmlFor="password-setup-tenant">Empresa</label>
                  <input
                    id="password-setup-tenant"
                    type="text"
                    value={pendingPasswordSetupSession.tenant_id}
                    readOnly
                  />
                  <small>Usuário {formValues.username.trim() || pendingPasswordSetupSession.operator_id}.</small>
                </div>

                <div className="field">
                  <label htmlFor="password-setup-new-password">Nova senha</label>
                  <input
                    id="password-setup-new-password"
                    name="password_setup_new_password"
                    type="password"
                    autoComplete="new-password"
                    value={passwordSetupValues.newPassword}
                    aria-invalid={Boolean(passwordSetupFieldErrors.newPassword)}
                    onChange={handlePasswordSetupFieldChange("newPassword")}
                  />
                  {passwordSetupFieldErrors.newPassword ? (
                    <p className="inline-error">{passwordSetupFieldErrors.newPassword}</p>
                  ) : (
                    <small>Após concluir, faça login novamente com a nova senha.</small>
                  )}
                </div>

                {passwordSetupError ? (
                  <p className="inline-error auth-submit-error" role="alert">
                    {passwordSetupError}
                  </p>
                ) : null}

                <button
                  className="cta auth-cta"
                  type="submit"
                  disabled={isPasswordSetupSubmitting}
                >
                  {isPasswordSetupSubmitting ? "Atualizando..." : "Concluir troca de senha"}
                </button>
                <button
                  className="action-button"
                  type="button"
                  onClick={handlePasswordSetupCancel}
                  disabled={isPasswordSetupSubmitting}
                >
                  Voltar ao login
                </button>
              </form>
            </div>
          ) : (
            <form className="form-grid" noValidate onSubmit={handleSubmit}>
              <div className="field">
                <label htmlFor="tenant-id">Código da empresa</label>
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
                  <small>Use o código informado pela sua equipe operacional.</small>
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
                  <small>Use o mesmo usuário autorizado para essa empresa.</small>
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
                  <small>Use a senha informada para a operação.</small>
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
          )}
        </section>
      </section>
    </div>
  );
}
