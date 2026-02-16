import Layout from '@theme/Layout';
import { JSX } from 'react';
import Button from '../components/Button';
import AnimatedOntosLogo from '../components/AnimatedOntosLogo';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import styles from './index.module.css';

const Hero = () => {
  const { siteConfig } = useDocusaurusContext();
  const brandName = (siteConfig.customFields?.brandName as string) || siteConfig.title;

  return (

  <header className={styles.heroBanner}>  
    <div className="px-4 md:px-10 min-h-screen flex flex-col justify-center items-center w-full">
      {/* Logo Section */}
      <div className={styles.imageOntos}>
        <AnimatedOntosLogo width={300} height={300} />
      </div>
      <h1 className={styles.centeredContent}>
        {brandName}
      </h1>
      <p className={styles.centeredContent}>
        A comprehensive data governance and management platform built for<a className={styles.spacedlink} href="https://www.databricks.com/product/unity-catalog">Databricks Unity Catalog.</a>
      </p>
      {/* Call to Action Buttons */}
      <div className={styles.centeredContent}>
        <div className={styles.buttonSpacing}>
        <Button
          variant="secondary"
          outline={true}
          link="/docs/introduction/motivation"
          size="large"
          label={"Motivation"}
          className="w-full md:w-auto"
        />
        </div>
        <div className={styles.buttonSpacing}>
        <Button
          variant="secondary"
          outline={true}
          link="/docs/category/getting-started"
          size="large"
          label={"Getting Started"}
          className="w-full md:w-auto"
        />
        </div>
        <div className={styles.buttonSpacing}>
        <Button
          variant="secondary"
          outline={true}
          link="/docs/faq"
          size="large"
          label="FAQ"
          className="w-full md:w-auto"
        />
        </div>
      </div>
    </div>
  </header>
  );
};

export default function Home(): JSX.Element {
  const { siteConfig } = useDocusaurusContext();
  const brandName = (siteConfig.customFields?.brandName as string) || siteConfig.title;

  return (
    <Layout title={brandName}>
      <main>
        <div className='flex justify-center mx-auto'>
          <div className='max-w-screen-lg'>
            <Hero />
          </div>
        </div>
      </main>
    </Layout>
  );
}
