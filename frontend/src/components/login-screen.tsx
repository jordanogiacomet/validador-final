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

type AuthMode = "login" | "setup" | "password_setup";
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

interface AuthFeature {
  title: string;
  description: string;
}

interface AuthModeContent {
  heroKicker: string;
  heroTitle: string;
  heroLead: string;
  panelTitle: string;
  panelCopy: string;
  features: AuthFeature[];
  pills: string[];
}

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

function getAuthModeContent(mode: AuthMode): AuthModeContent {
  switch (mode) {
    case "setup":
      return {
        heroKicker: "Primeiro acesso",
        heroTitle: "Configure o primeiro administrador sem misturar essa etapa ao login comum.",
        heroLead:
          "Use este fluxo apenas na montagem inicial do ambiente. Depois de concluir, o acesso volta ao login normal do dia a dia.",
        panelTitle: "Criar o administrador inicial",
        panelCopy:
          "Preencha somente o que for necessario para liberar o primeiro acesso do ambiente.",
        features: [
          {
            title: "Uso unico",
            description:
              "Este formulario existe apenas enquanto o ambiente ainda nao tem administrador persistido.",
          },
          {
            title: "Configuracao inicial",
            description:
              "Crie o primeiro usuario responsavel pelo ambiente antes de convidar ou cadastrar os demais.",
          },
          {
            title: "Volta simples",
            description:
              "Assim que concluir, o proximo passo e entrar pelo login comum com esse usuario.",
          },
        ],
        pills: ["Fluxo separado", "Sem tela concorrente", "Volta ao login"],
      };
    case "password_setup":
      return {
        heroKicker: "Troca obrigatoria",
        heroTitle: "Atualize a senha temporaria antes de abrir a area operacional.",
        heroLead:
          "Este estado aparece so no primeiro acesso de contas obrigadas a trocar a senha. Conclua a etapa e volte ao login com a nova senha.",
        panelTitle: "Trocar a senha temporaria",
        panelCopy:
          "Use esta tela apenas para definir a nova senha e liberar o acesso definitivo do usuario.",
        features: [
          {
            title: "Sessao temporaria",
            description:
              "A senha atual serve apenas para concluir esta etapa. Ela nao deve continuar em uso.",
          },
          {
            title: "Nova senha",
            description:
              "Defina a senha definitiva agora para evitar bloqueio ou retrabalho na proxima entrada.",
          },
          {
            title: "Retorno controlado",
            description:
              "Depois de salvar, o sistema volta ao login para iniciar a sessao operacional ja com a nova credencial.",
          },
        ],
        pills: ["Primeiro login", "Sem acesso parcial", "Retorno ao login"],
      };
    case "login":
    default:
      return {
        heroKicker: "Acesso operacional",
        heroTitle: "Entre e continue a conferencia patrimonial sem passos concorrentes.",
        heroLead:
          "A tela principal agora mostra apenas o que voce precisa para entrar. Se o ambiente ainda estiver em montagem, use o fluxo separado de primeiro acesso.",
        panelTitle: "Entrar na area operacional",
        panelCopy:
          "Informe empresa, usuario e senha. Depois disso voce ja pode enviar a planilha e revisar o lote.",
        features: [
          {
            title: "Empresa certa",
            description:
              "Confirme o codigo da empresa antes de entrar para manter o contexto operacional correto.",
          },
          {
            title: "Usuario certo",
            description:
              "Use o mesmo usuario liberado para essa empresa. O sistema valida o escopo no login.",
          },
          {
            title: "Continuacao direta",
            description:
              "Entrou, abriu o lote e seguiu para upload, acompanhamento e revisao sem trocar de tela.",
          },
        ],
        pills: ["Login comum", "Empresa explicita", "Pronto para operar"],
      };
  }
}

function shouldShowDevLoginHints(): boolean {
  return process.env.NEXT_PUBLIC_SHOW_DEV_LOGIN_HINTS === "true";
}

function appendSupportCode(message: string, error: unknown): string {
  if (error instanceof ApiError && error.requestId) {
    return `${message} Codigo de suporte: ${error.requestId}.`;
  }

  return message;
}

function validateLoginForm(values: LoginFormState): LoginFieldErrors {
  const errors: LoginFieldErrors = {};
  const normalizedTenantId = values.tenantId.trim();
  const normalizedUsername = values.username.trim();

  if (!normalizedTenantId) {
    errors.tenantId = "Informe o codigo da empresa.";
  } else if (!TENANT_ID_PATTERN.test(normalizedTenantId)) {
    errors.tenantId = "Use apenas letras, numeros, ponto, hifen ou underscore.";
  }

  if (!normalizedUsername) {
    errors.username = "Informe o usuario autorizado para essa empresa.";
  } else if (!USERNAME_PATTERN.test(normalizedUsername)) {
    errors.username = "Use apenas letras, numeros, ponto, arroba, hifen ou underscore.";
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
    errors.username = "Informe o usuario administrador.";
  } else if (!USERNAME_PATTERN.test(normalizedUsername)) {
    errors.username = "Use apenas letras, numeros, ponto, arroba, hifen ou underscore.";
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
      return appendSupportCode("Credenciais invalidas. Revise usuario e senha.", error);
    }

    if (error.status === 404) {
      return appendSupportCode("Empresa inexistente. Revise o codigo informado.", error);
    }

    if (error.status === 403) {
      if (error.detail === "Operator is not allowed for this tenant") {
        return appendSupportCode("Este usuario nao pode acessar a empresa informada.", error);
      }

      if (error.detail === "Operator is disabled") {
        return appendSupportCode("Este usuario esta desabilitado.", error);
      }

      return appendSupportCode("Acesso negado para a empresa informada.", error);
    }

    return error.message;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Nao foi possivel iniciar a sessao operacional.";
}

function getSetupErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return appendSupportCode("Token de setup invalido.", error);
    }

    if (error.status === 409) {
      return appendSupportCode("O primeiro acesso ja foi configurado.", error);
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

  return "Nao foi possivel criar o administrador inicial.";
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
      return appendSupportCode("A sessao temporaria expirou. Entre novamente.", error);
    }

    if (error.status === 403) {
      return appendSupportCode(
        "Esta sessao exige a troca imediata de senha antes do acesso.",
        error,
      );
    }

    if (error.status === 409) {
      return appendSupportCode(
        "A troca obrigatoria de senha ja foi concluida para este usuario.",
        error,
      );
    }

    return error.message;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Nao foi possivel concluir a troca obrigatoria de senha.";
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const showDevLoginHints = shouldShowDevLoginHints();
  const [authMode, setAuthMode] = useState<AuthMode>("login");
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

  useEffect(() => {
    if (pendingPasswordSetupSession) {
      setAuthMode("password_setup");
      return;
    }

    setAuthMode((currentValue) => {
      if (currentValue === "password_setup") {
        return "login";
      }

      if (currentValue === "setup" && !setupState?.available) {
        return "login";
      }

      return currentValue;
    });
  }, [pendingPasswordSetupSession, setupState]);

  const activeMode: AuthMode = pendingPasswordSetupSession ? "password_setup" : authMode;
  const activeContent = getAuthModeContent(activeMode);
  const canShowSetupMode = Boolean(setupState?.available);

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

  function handleAuthModeChange(nextMode: Exclude<AuthMode, "password_setup">) {
    setAuthMode(nextMode);
    setSubmitError(null);
    setFieldErrors({});
    setSetupError(null);
    setSetupFieldErrors({});
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
      setAuthMode("login");
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
      setSetupSuccess("Administrador inicial criado. Entre com o usuario criado.");
      setAuthMode("login");
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
        "Senha temporaria atualizada. Entre novamente com a nova senha.",
      );
      setFormValues((currentValue) => ({
        ...currentValue,
        password: "",
      }));
      setAuthMode("login");
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
    setAuthMode("login");
  }

  return (
    <div className="auth-shell">
      <section className="auth-layout">
        <div className="auth-hero">
          <div className="panel-kicker auth-kicker">{activeContent.heroKicker}</div>
          <h1 className="auth-heading">{activeContent.heroTitle}</h1>
          <p className="auth-lead">{activeContent.heroLead}</p>

          <div className="auth-feature-grid">
            {activeContent.features.map((feature) => (
              <article className="auth-feature-card" key={feature.title}>
                <strong>{feature.title}</strong>
                <p>{feature.description}</p>
              </article>
            ))}
          </div>

          <div className="auth-trust-row" aria-label="Atalhos do fluxo inicial">
            {activeContent.pills.map((pill) => (
              <span className="auth-trust-pill" key={pill}>
                {pill}
              </span>
            ))}
          </div>
        </div>

        <section className="panel auth-panel">
          <div className="panel-kicker">Acesso</div>
          <h2 className="panel-title auth-title">{activeContent.panelTitle}</h2>
          <p className="panel-copy auth-copy">{activeContent.panelCopy}</p>

          <div className="auth-panel-stack">
            {canShowSetupMode && activeMode !== "password_setup" ? (
              <div className="auth-mode-switcher" aria-label="Escolha o fluxo de acesso">
                <button
                  className={`auth-mode-button${activeMode === "login" ? " is-active" : ""}`}
                  type="button"
                  aria-pressed={activeMode === "login"}
                  onClick={() => handleAuthModeChange("login")}
                >
                  Login comum
                </button>
                <button
                  className={`auth-mode-button${activeMode === "setup" ? " is-active" : ""}`}
                  type="button"
                  aria-pressed={activeMode === "setup"}
                  onClick={() => handleAuthModeChange("setup")}
                >
                  Primeiro acesso
                </button>
              </div>
            ) : null}

            {setupSuccess && activeMode === "login" ? (
              <div className="auth-bootstrap-card auth-setup-success" role="status">
                <div className="auth-bootstrap-head">
                  <div>
                    <span className="auth-bootstrap-label">Primeiro acesso</span>
                    <strong>{setupSuccess}</strong>
                  </div>
                  <span className="auth-bootstrap-badge">concluido</span>
                </div>
              </div>
            ) : null}

            {passwordSetupSuccess && activeMode === "login" ? (
              <div className="auth-bootstrap-card auth-setup-success" role="status">
                <div className="auth-bootstrap-head">
                  <div>
                    <span className="auth-bootstrap-label">Senha temporaria</span>
                    <strong>{passwordSetupSuccess}</strong>
                  </div>
                  <span className="auth-bootstrap-badge">concluido</span>
                </div>
              </div>
            ) : null}

            {activeMode === "login" && canShowSetupMode ? (
              <div className="auth-bootstrap-card auth-context-card">
                <div className="auth-bootstrap-head">
                  <div>
                    <span className="auth-bootstrap-label">Fluxo separado</span>
                    <strong>Ambiente sem administrador?</strong>
                  </div>
                  <span className="auth-bootstrap-badge">uso unico</span>
                </div>
                <p className="auth-bootstrap-note">
                  Se este ambiente ainda nao tiver um administrador inicial, troque para
                  &quot;Primeiro acesso&quot; antes de tentar entrar pelo login comum.
                </p>
              </div>
            ) : null}

            {activeMode === "setup" && setupState?.available ? (
              <div className="auth-bootstrap-card auth-context-card">
                <div className="auth-bootstrap-head">
                  <div>
                    <span className="auth-bootstrap-label">Antes de continuar</span>
                    <strong>Use esta etapa apenas na configuracao inicial</strong>
                  </div>
                  <span className="auth-bootstrap-badge">contexto</span>
                </div>
                <ul className="auth-context-list">
                  <li>Empresa inicial: {setupState.tenant_id ?? "definida no ambiente"}.</li>
                  <li>
                    {setupState.requires_setup_token
                      ? "Tenha o token de setup em maos antes de criar o usuario."
                      : "Este ambiente nao exige token adicional para o primeiro acesso."}
                  </li>
                  <li>Depois de criar o administrador, volte ao login comum com esse usuario.</li>
                </ul>
              </div>
            ) : null}

            {activeMode === "password_setup" && pendingPasswordSetupSession ? (
              <div className="auth-bootstrap-card auth-context-card">
                <div className="auth-bootstrap-head">
                  <div>
                    <span className="auth-bootstrap-label">Troca obrigatoria</span>
                    <strong>Conclua esta etapa para liberar o acesso</strong>
                  </div>
                  <span className="auth-bootstrap-badge">primeiro login</span>
                </div>
                <ul className="auth-context-list">
                  <li>Empresa: {pendingPasswordSetupSession.tenant_id}.</li>
                  <li>
                    Usuario: {formValues.username.trim() || pendingPasswordSetupSession.operator_id}.
                  </li>
                  <li>Depois da troca, o sistema volta ao login para abrir a sessao normal.</li>
                </ul>
              </div>
            ) : null}

            {showDevLoginHints && activeMode === "login" ? (
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
                    <dt>Usuario inicial</dt>
                    <dd>{INITIAL_ACCESS.username}</dd>
                  </div>
                </dl>
                <p className="auth-bootstrap-note">
                  Esta dica so aparece quando NEXT_PUBLIC_SHOW_DEV_LOGIN_HINTS=true.
                </p>
              </div>
            ) : null}
          </div>

          {activeMode === "setup" ? (
            <form className="form-grid auth-setup-form" noValidate onSubmit={handleSetupSubmit}>
              <div className="field">
                <label htmlFor="setup-username">Usuario administrador</label>
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
                  <small>Esse usuario sera vinculado a empresa inicial do ambiente.</small>
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
                  <small>A senha nao e exibida nem armazenada em texto puro.</small>
                )}
              </div>

              {setupState?.requires_setup_token ? (
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

              <div className="auth-form-actions">
                <button className="cta auth-cta" type="submit" disabled={isSetupSubmitting}>
                  {isSetupSubmitting ? "Criando..." : "Criar administrador"}
                </button>
                <button
                  className="action-button"
                  type="button"
                  onClick={() => handleAuthModeChange("login")}
                  disabled={isSetupSubmitting}
                >
                  Voltar ao login
                </button>
              </div>
            </form>
          ) : activeMode === "password_setup" && pendingPasswordSetupSession ? (
            <form className="form-grid auth-setup-form" noValidate onSubmit={handlePasswordSetupSubmit}>
              <div className="field">
                <label htmlFor="password-setup-tenant">Empresa</label>
                <input
                  id="password-setup-tenant"
                  type="text"
                  value={pendingPasswordSetupSession.tenant_id}
                  readOnly
                />
                <small>
                  Usuario {formValues.username.trim() || pendingPasswordSetupSession.operator_id}.
                </small>
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
                  <small>Depois de concluir, faca login novamente com a nova senha.</small>
                )}
              </div>

              {passwordSetupError ? (
                <p className="inline-error auth-submit-error" role="alert">
                  {passwordSetupError}
                </p>
              ) : null}

              <div className="auth-form-actions">
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
              </div>
            </form>
          ) : (
            <form className="form-grid" noValidate onSubmit={handleSubmit}>
              <div className="field">
                <label htmlFor="tenant-id">Codigo da empresa</label>
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
                  <small>Use o codigo informado pela sua equipe operacional.</small>
                )}
              </div>

              <div className="field">
                <label htmlFor="username">Usuario</label>
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
                  <small>Use o mesmo usuario autorizado para essa empresa.</small>
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
                  <small>Use a senha informada para a operacao.</small>
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
