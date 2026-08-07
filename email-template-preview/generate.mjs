import { mkdir, writeFile } from "node:fs/promises"
import { join } from "node:path"

const outputDir = join(process.cwd(), "frontend", "public", "email-preview")

const templates = [
  {
    filename: "verify-email-email.html",
    documentTitle: "Confirm your email",
    preheader: "Use this one-time code to finish setting up your Oreag account.",
    glyph: "&#10003;",
    title: "Confirm your email",
    intro: "Finish setting up your Oreag account by entering the code below.",
    code: "086433",
    button: "Confirm with one click",
    href: "https://oreag.vercel.app/verify",
    safetyTitle: "Didn&apos;t create an account?",
    safetyText: "You can ignore this email. Nothing is created unless the code or link is used.",
  },
  {
    filename: "sign-in-code-email.html",
    documentTitle: "Your sign-in code",
    preheader: "Use this one-time code to securely sign in to Oreag.",
    glyph: "&#8594;",
    title: "Your sign-in code",
    intro: "Use the code below to securely sign in to your Oreag workspace.",
    code: "919544",
    button: "Sign in with one click",
    href: "https://oreag.vercel.app/sign-in",
    safetyTitle: "Didn&apos;t try to sign in?",
    safetyText: "You can ignore this email. Your account is safe and nothing changes unless the code or link is used.",
  },
  {
    filename: "password-reset-email.html",
    documentTitle: "Reset your password",
    preheader: "Use this one-time code to continue securely and choose a new password.",
    glyph: "&#8635;",
    title: "Reset your password",
    intro: "Use the code below to continue securely and choose a new password.",
    code: "783696",
    button: "Choose a new password",
    href: "https://oreag.vercel.app/reset-password",
    safetyTitle: "Didn&apos;t request a reset?",
    safetyText: "You can ignore this email. Your password will not change unless the code or link is used.",
  },
]

function codeCells(code) {
  return [...code]
    .map(
      (digit, index) => `${index ? '<td class="code-gap" width="8" style="width:8px;font-size:1px;line-height:1px;">&nbsp;</td>' : ""}
                <td class="code-cell" align="center" height="60" style="height:60px;border:1px solid #deddea;border-radius:10px;background-color:#f7f6fb;font-family:'Courier New',Courier,monospace;font-size:30px;font-weight:bold;line-height:60px;color:#17181a;">${digit}</td>`
    )
    .join("")
}

function renderEmail(template) {
  return `<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <title>${template.documentTitle}</title>
  <!--[if mso]>
  <style>table,td,a{font-family:Arial,Helvetica,sans-serif!important;}</style>
  <![endif]-->
  <style>
    body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
    table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
    img { -ms-interpolation-mode: bicubic; }
    table { border-collapse: collapse !important; }
    @media screen and (max-width: 620px) {
      .outer-pad { padding: 16px 10px 28px !important; }
      .email-card { width: 100% !important; max-width: 100% !important; }
      .brand-pad { padding: 16px 18px !important; }
      .content-pad { padding: 28px 20px 26px !important; }
      .email-title { font-size: 24px !important; line-height: 30px !important; }
      .email-copy { font-size: 15px !important; line-height: 23px !important; }
      .purpose-icon { width: 54px !important; height: 54px !important; font-size: 23px !important; line-height: 54px !important; }
      .code-wrap { padding: 14px 0 !important; }
      .code-cell { height: 48px !important; font-size: 25px !important; line-height: 48px !important; border-radius: 8px !important; }
      .code-gap { width: 5px !important; }
      .cta-link { padding: 14px 12px !important; font-size: 14px !important; }
      .safety-pad { padding: 14px !important; }
      .footer-pad { padding: 20px 16px 22px !important; }
    }
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;word-spacing:normal;">
  <div style="display:none;font-size:1px;color:#f3f4f6;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">${template.preheader}</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;background-color:#f3f4f6;">
    <tr>
      <td class="outer-pad" align="center" style="padding:34px 16px 48px;">
        <!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560"><tr><td><![endif]-->
        <table class="email-card" role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="width:100%;max-width:560px;border:1px solid #dedfe3;border-radius:18px;background-color:#ffffff;box-shadow:0 10px 30px rgba(23,24,26,0.05);overflow:hidden;">
          <tr>
            <td class="brand-pad" style="padding:18px 24px;border-bottom:1px solid #e7e8eb;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="36" height="36" align="center" style="width:36px;height:36px;border:1px solid #dedfe3;border-radius:9px;background-color:#f5f5f6;font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:bold;line-height:36px;color:#17181a;">
                    R
                  </td>
                  <td style="padding-left:11px;font-family:Helvetica,Arial,sans-serif;font-size:18px;font-weight:bold;line-height:36px;color:#17181a;">Oreag</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="content-pad" style="padding:38px 42px 34px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td align="center" style="padding-bottom:20px;">
                    <div class="purpose-icon" style="width:60px;height:60px;border:1px solid #e2e0ef;border-radius:50%;background-color:#f0eff8;font-family:Helvetica,Arial,sans-serif;font-size:25px;font-weight:bold;line-height:60px;color:#3d3b5c;text-align:center;">${template.glyph}</div>
                  </td>
                </tr>
                <tr>
                  <td class="email-title" align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:28px;font-weight:bold;line-height:35px;letter-spacing:-0.4px;color:#17181a;padding-bottom:12px;">${template.title}</td>
                </tr>
                <tr>
                  <td class="email-copy" align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:24px;color:#5d6269;padding:0 8px 24px;">${template.intro}</td>
                </tr>
                <tr>
                  <td class="code-wrap" align="center" style="padding:16px 0;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="420" style="width:100%;max-width:420px;table-layout:fixed;">
                      <tr>${codeCells(template.code)}
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:13px;line-height:20px;color:#7a8087;padding:2px 0 24px;">This code expires shortly and can only be used once.</td>
                </tr>
                <tr>
                  <td style="padding-bottom:24px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                      <tr>
                        <td align="center" bgcolor="#17181a" style="border-radius:10px;mso-padding-alt:15px 20px;">
                          <a class="cta-link" href="${template.href}" style="display:block;padding:15px 20px;font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:bold;line-height:20px;color:#ffffff;text-align:center;text-decoration:none;">${template.button}</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding-bottom:20px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                      <tr>
                        <td height="1" style="height:1px;font-size:1px;line-height:1px;background-color:#e7e8eb;">&nbsp;</td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td class="safety-pad" style="padding:16px;border:1px solid #e7e8eb;border-radius:12px;background-color:#fafafa;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                      <tr>
                        <td width="34" valign="top" style="width:34px;padding-right:12px;">
                          <div style="width:32px;height:32px;border-radius:50%;background-color:#f0eff8;font-family:Helvetica,Arial,sans-serif;font-size:16px;font-weight:bold;line-height:32px;color:#3d3b5c;text-align:center;">&#10003;</div>
                        </td>
                        <td valign="top" style="font-family:Helvetica,Arial,sans-serif;font-size:13px;line-height:20px;color:#6d7279;">
                          <strong style="color:#2c2f33;">${template.safetyTitle}</strong><br>
                          ${template.safetyText}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:12px;line-height:19px;color:#858a91;padding-top:18px;">Never share this code. Oreag support will never ask for it.</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="footer-pad" align="center" style="padding:22px 24px 24px;border-top:1px solid #e7e8eb;font-family:Helvetica,Arial,sans-serif;font-size:12px;line-height:19px;color:#92979e;">
              Oreag &middot; RAG &amp; Memory as a Service<br>
              <a href="https://oreag.vercel.app" style="color:#6f747b;text-decoration:underline;">oreag.vercel.app</a><br>
              <span style="color:#a1a5ab;">Transactional account email</span>
            </td>
          </tr>
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>
`
}

await mkdir(outputDir, { recursive: true })

for (const template of templates) {
  await writeFile(join(outputDir, template.filename), renderEmail(template), "utf8")
}

console.log(outputDir)
