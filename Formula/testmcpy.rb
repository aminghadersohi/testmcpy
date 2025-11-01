class Testmcpy < Formula
  include Language::Python::Virtualenv

  desc "MCP Testing Framework - Test LLM tool calling with MCP services"
  homepage "https://github.com/preset-io/testmcpy"
  url "https://files.pythonhosted.org/packages/source/t/testmcpy/testmcpy-0.1.0.tar.gz"
  sha256 "a4ab54bb171a66bb60381f3257f194b2b29ba5df2bac8c826aa846884ec3bb28"
  license "Apache-2.0"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "MCP Testing Framework", shell_output("#{bin}/testmcpy --help")
  end
end
